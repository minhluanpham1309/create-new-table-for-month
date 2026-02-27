import json
import logging
import pymysql
import ssl
import os
import boto3
import redis
from typing import Dict, List, Optional, Set
import threading
from botocore.config import Config
from dotenv import load_dotenv
import pytz

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
PATTERN_YYYYMM = "%Y%m"
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

CACHE_KEY_PREFIX  = "heatmap:cache:"
CACHE_DOMAIN      = f"{CACHE_KEY_PREFIX}domain"
CACHE_UTM_SOURCE  = f"{CACHE_KEY_PREFIX}utm_source"
CACHE_UTM_MEDIUM  = f"{CACHE_KEY_PREFIX}utm_medium"

BATCH_SIZE   = 500
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
# GLOBAL SINGLETONS  (initialized once per Lambda container)
# ============================================================================

_redis_pool: Optional[redis.ConnectionPool] = None
_redis_client: Optional[redis.Redis] = None
_secret_cache: Optional[Dict] = None          # cache secret within same invocation
_redis_lock = threading.Lock()


def get_max_workers() -> int:
    return int(os.environ.get("MAX_WORKERS", 10))


def get_redis_client() -> redis.Redis:
    """
    Return a thread-safe Redis client backed by a connection pool.
    Uses a Lock to prevent duplicate pool creation when multiple threads
    call this concurrently before the singleton is ready.
    """
    global _redis_pool, _redis_client
    if _redis_client is None:
        with _redis_lock:
            # Double-checked locking: re-check after acquiring lock
            if _redis_client is None:
                redis_host     = os.environ["REDIS_HOST"]
                redis_port     = int(os.environ.get("REDIS_PORT", 6379))
                redis_password = os.environ.get("REDIS_PASSWORD") or None

                _redis_pool = redis.ConnectionPool(
                    host=redis_host,
                    port=redis_port,
                    password=redis_password,
                    db=1,
                    decode_responses=True,
                    max_connections=20,
                    socket_connect_timeout=5,
                    socket_timeout=5,
                )
                _redis_client = redis.Redis(connection_pool=_redis_pool)
                _redis_client.ping()
                logger.info("Redis connection pool initialized")
    return _redis_client


# ============================================================================
# AWS HELPERS
# ============================================================================

def get_region() -> str:
    return os.environ.get("AWS_REGION", "ap-northeast-1")


def get_secret(region):
    global _secret_cache
    if _secret_cache is not None:
        return _secret_cache

    secret_name = os.environ.get('RDS_SECRET_NAME', 'rds/db-test-private')
    # Create client with timeout config
    config = Config(
        connect_timeout=5,
        read_timeout=10,
        retries={'max_attempts': 3}
    )

    logger.info("Creating boto3 client for Secrets Manager...")
    client = boto3.client('secretsmanager', region_name=region, config=config)

    logger.info("Fetching secret value from Secrets Manager...")
    response = client.get_secret_value(SecretId=secret_name)
    _secret_cache = json.loads(response["SecretString"])
    logger.info("Secret fetched from Secrets Manager")
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

        logger.info(f"Loading CA bundle from: {ca_file_path}")

        # Create SSL context with TLS 1.2+
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ssl_context.load_verify_locations(cafile=ca_file_path)

        # Configure verification
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        logger.info("SSL: VERIFY_CA")

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
            "host": secret.get("host", os.getenv("DB_HOST")),
            "port": int(secret.get("port", os.getenv("DB_PORT", 3306))),
            "user": secret.get("username", os.getenv("DB_USER")),
            "password": secret.get("password", os.getenv("DB_PASSWORD")),
            "database": secret.get("dbname", os.getenv("DB_NAME", "HEAT_MAP")),
            "charset": "utf8mb4",
            "connect_timeout": 10,
            "cursorclass": pymysql.cursors.DictCursor,
            "ssl": ssl_context,
        }

        logger.info("Connecting to database...")
        connection = pymysql.connect(**db_config)
        logger.info("Database connection established")
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
    try:
        logger.info("")
        logger.info(f"====== START STEP: {step_name} ======")
        result = func(*args, **kwargs)
        logger.info(f"====== DONE STEP: {step_name} ======")
        logger.info("")
        return result
    except Exception as e:
        logger.error(f"====== ERROR STEP: {step_name} ======")
        logger.error(f"Exception: {str(e)}")
        logger.error("")
        raise


# ============================================================================
# REDIS HELPERS
# ============================================================================

def scan_redis_keys(pattern: str) -> List[str]:
    """
    Use SCAN instead of KEYS to avoid blocking Redis.
    O(N) but non-blocking and cursor-based.
    """
    rc     = get_redis_client()
    keys   = []
    cursor = 0
    while True:
        cursor, batch = rc.scan(cursor=cursor, match=pattern, count=1000)
        keys.extend(batch)
        if cursor == 0:
            break
    logger.info(f"SCAN found {len(keys)} keys for pattern: {pattern}")
    return keys


def get_redis_set_data(key: str) -> Set[str]:
    try:
        data = get_redis_client().smembers(key)
        return data if data else set()
    except Exception:
        logger.exception(f"smembers failed for key: {key}")
        return set()


def delete_redis_key(key: str) -> bool:
    try:
        get_redis_client().delete(key)
        return True
    except Exception:
        logger.exception(f"delete failed for key: {key}")
        return False


def get_from_redis_cache(cache_key: str, field: str) -> Optional[int]:
    try:
        val = get_redis_client().hget(cache_key, field)
        return int(val) if val is not None else None
    except Exception:
        logger.exception(f"hget failed [{cache_key}][{field}]")
        return None


def set_to_redis_cache(cache_key: str, field: str, id_value: int) -> None:
    try:
        get_redis_client().hset(cache_key, field, str(id_value))
    except Exception:
        logger.exception(f"hset failed [{cache_key}][{field}]")
