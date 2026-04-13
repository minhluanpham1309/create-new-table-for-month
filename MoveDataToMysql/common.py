import json
import logging
import pymysql
import ssl
import os
import boto3
from typing import Dict, List, Optional, Set
import threading
from botocore.config import Config
from dotenv import load_dotenv
import pytz

from redis_wrapper import RedisWrapper

# Load environment variables from .env file only when running locally
if not os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
    load_dotenv()

# ============================================================================
# LOGGING
# ============================================================================
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ============================================================================
# CONSTANTS
# ============================================================================
JST = pytz.timezone('Asia/Tokyo')

PATTERN_YYYY_MM_DD_HH = "%Y-%m-%d %H"
PATTERN_YYYYMM        = "%Y%m"
CHUNK_INDEX_TRACKING_DATA_KEY = ":chunk"
DELIMITER = ";-;"

ORGANIC_PAGES = [
    "www.google.",
    "search.yahoo.co.jp",
    "www.bing.com",
]

SOCIAL_PAGES = [
    "facebook.com",
    "twitter.com",
    "linkedin.com",
    "t.co",
    "matome.naver.jp",
    "plus.google.com",
    "oshiete.goo.ne.jp",
    "okwave.jp",
    "b.hatena.ne.jp",
]

CACHE_KEY_PREFIX = "heatmap:cache:"
CACHE_DOMAIN     = f"{CACHE_KEY_PREFIX}domain"
CACHE_UTM_SOURCE = f"{CACHE_KEY_PREFIX}utm_source"
CACHE_UTM_MEDIUM = f"{CACHE_KEY_PREFIX}utm_medium"

BATCH_SIZE         = 500
MAX_DEADLOCK_RETRY = 3

# ============================================================================
# ENUMS
# ============================================================================
from enum import Enum


class ReferrerDomainType(Enum):
    NONE    = 0
    ORGANIC = 1
    SOCIAL  = 2


class CacheType(Enum):
    DOMAIN     = "domain"
    UTM_SOURCE = "utm_source"
    UTM_MEDIUM = "utm_medium"


# ============================================================================
# GLOBAL SINGLETONS  (initialized once per Lambda container / warm start)
#
# Singleton pattern is intentional: reusing connection pools across invocations
# avoids TCP + TLS handshake overhead on every call (~15-60ms per connection).
#
# DNS caching risk (stale IP after ElastiCache failover):
#   Mitigated by health_check_interval=30 — redis-py sends PING before each
#   command if connection was idle > 30s. Dead connection triggers reconnect,
#   which re-resolves DNS and picks up the new primary IP automatically.
#   socket_keepalive=True adds OS-level TCP keepalive for faster dead detection.
# ============================================================================

_wrappers: Dict[str, RedisWrapper] = {}
_locks: Dict[str, threading.Lock] = {
    "data":    threading.Lock(),
    "package": threading.Lock(),
    "setting":  threading.Lock(),
}

_secret_cache: Optional[Dict] = None


def get_max_workers() -> int:
    return int(os.environ.get("MAX_WORKERS", 10))


def _get_wrapper(label: str, host: str, port: int, password: Optional[str], db: int) -> RedisWrapper:
    """Generic double-checked locking singleton getter for RedisWrapper."""
    if label not in _wrappers:
        with _locks[label]:
            if label not in _wrappers:
                _wrappers[label] = RedisWrapper(
                    host=host,
                    port=port,
                    password=password,
                    db=db,
                    max_connections=20,  # threads + small buffer
                    socket_connect_timeout=5,               # fail fast: Lambda→ElastiCache < 10ms
                    socket_timeout=5,                       # allow time for read/write ops
                )
                logger.info(f"RedisWrapper initialized: label={label} host={host} port={port} db={db}")
    return _wrappers[label]


def _redis_host() -> str:
    return os.environ["REDIS_HOST"]

def _redis_port() -> int:
    return int(os.environ.get("REDIS_PORT", 6380))

def _redis_password() -> Optional[str]:
    return os.environ.get("REDIS_PASSWORD") or None


def get_data_redis_wrapper() -> RedisWrapper:
    """Data Redis wrapper — REDIS_HOST, db=1."""
    return _get_wrapper("data", _redis_host(), _redis_port(), _redis_password(), db=1)


def get_package_redis_wrapper() -> RedisWrapper:
    """Package Redis wrapper — REDIS_NETTY_HOST, db=0."""
    return _get_wrapper(
        "package",
        host=os.environ["REDIS_NETTY_HOST"],
        port=_redis_port(),
        password=_redis_password(),
        db=0,
    )


def get_setting_wrapper() -> RedisWrapper:
    """setting wrapper — REDIS_HOST, db=0. Used for domain/utm_source/utm_medium caches."""
    return _get_wrapper("setting", _redis_host(), _redis_port(), _redis_password(), db=0)


# ============================================================================
# AWS HELPERS
# ============================================================================

def get_region() -> str:
    return os.environ.get("AWS_REGION", "ap-northeast-1")


def get_secret(region):
    global _secret_cache
    if _secret_cache is not None:
        return _secret_cache

    secret_name = os.environ.get("RDS_SECRET_NAME", "rds/heatmap-db-secret")
    # Create client with timeout config
    config = Config(
        connect_timeout=5,
        read_timeout=10,
        retries={'max_attempts': 3}
    )
    
    client = boto3.client('secretsmanager', region_name=region, config=config)
    response = client.get_secret_value(SecretId=secret_name)
    _secret_cache = json.loads(response["SecretString"])
    return _secret_cache


# ============================================================================
# SSL / DB CONNECTION
# ============================================================================

def get_ssl_context(region: str = "ap-northeast-1"):
    """Create SSL context with TLS 1.2+ (download CA bundle from AWS)"""
    try:
        ca_file_path = os.path.join(os.path.dirname(__file__), "certs", f"{region}-bundle.pem")
        
        # Fallback to global bundle if region-specific not found
        if not os.path.exists(ca_file_path):
            ca_file_path = os.path.join(os.path.dirname(__file__), "certs", "global-bundle.pem")
        
        if not os.path.exists(ca_file_path):
            raise FileNotFoundError(f"CA bundle not found at {ca_file_path}")
        
        # Create SSL context with TLS 1.2+
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ssl_context.load_verify_locations(cafile=ca_file_path)
        
        # Configure verification
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        # Set minimum TLS 1.2
        ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
        
        return ssl_context
    
    except Exception as e:
        logger.error(f"Failed to create SSL context: {str(e)}")
        raise


def get_db_connection(secret):
    try:
        ssl_context = get_ssl_context()
        
        db_config = {
            "host":            secret.get("host",     os.getenv("DB_HOST")),
            "port":            int(secret.get("port", os.getenv("DB_PORT", 3306))),
            "user":            secret.get("username", os.getenv("DB_USER")),
            "password":        secret.get("password", os.getenv("DB_PASSWORD")),
            "database":        secret.get("dbname",   os.getenv("DB_NAME", "HEAT_MAP")),
            "charset":         "utf8mb4",
            "connect_timeout": 10,
            "cursorclass":     pymysql.cursors.DictCursor,
            "ssl":             ssl_context,
        }
        connection = pymysql.connect(**db_config)
        return connection
    
    
    except pymysql.err.OperationalError as e:
        error_code = e.args[0] if e.args else None
        if error_code == 2003:
            logger.error("Cannot connect to database server")
        elif error_code == 1045:
            logger.error("Access denied - check username/password")
        else:
            logger.error(f"Database connection error: {str(e)}")
        raise
    
    except Exception as e:
        logger.error(f"Failed to connect to database: {str(e)}")
        raise


# ============================================================================
# STEP RUNNER
# ============================================================================

def run_step(step_name: str, func, *args, **kwargs):
    """
    Execute a step with timing and error logging.
    Logs start time, end time, and elapsed time for performance tracking.
    """
    from datetime import datetime

    start_time = datetime.now(JST)
    logger.info(f"[START] {step_name}")

    try:
        result = func(*args, **kwargs)
        elapsed = (datetime.now(JST) - start_time).total_seconds()
        logger.info(f"[SUCCESS] {step_name} — elapsed={elapsed:.2f}s")
        return result
    except Exception as e:
        elapsed = (datetime.now(JST) - start_time).total_seconds()
        logger.error(f"[ERROR] {step_name} — elapsed={elapsed:.2f}s — {str(e)}")
        raise


# ============================================================================
# REDIS HELPERS
# ============================================================================

def scan_redis_keys(pattern: str) -> List[str]:
    """SCAN instead of KEYS to avoid blocking Redis. O(N) but non-blocking."""
    try:
        return get_data_redis_wrapper().scan(pattern)
    except Exception:
        logger.error(f"scan failed for pattern: {pattern}")
        return []


def get_redis_set_data(key: str) -> Set[str]:
    try:
        return get_data_redis_wrapper().smembers(key)
    except Exception:
        logger.error(f"smembers failed for key: {key}")
        return set()


def delete_redis_key(key: str) -> bool:
    try:
        get_data_redis_wrapper().delete(key)
        return True
    except Exception:
        logger.error(f"delete failed for key: {key}")
        return False


def get_from_setting_cache(cache_key: str, field: str) -> Optional[int]:
    """Read int from setting db=0 (domain/utm caches)."""
    try:
        return get_setting_wrapper().hget_int(cache_key, field)
    except Exception:
        logger.error(f"hget_int (setting db=0) failed [{cache_key}][{field}]")
        return None


def set_to_setting_cache(cache_key: str, field: str, id_value: int) -> None:
    """Write int to setting db=0 (domain/utm caches)."""
    try:
        get_setting_wrapper().hset_int(cache_key, field, id_value)
    except Exception:
        logger.error(f"hset_int (setting db=0) failed [{cache_key}][{field}]")