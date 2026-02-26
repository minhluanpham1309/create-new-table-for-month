import json
import logging
import pymysql
import ssl
import os
import boto3
import redis
import hashlib
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Optional, Any, Set
from enum import Enum
from urllib.parse import unquote
import pytz
from dotenv import load_dotenv

# Load environment variables from .env file only when running locally
if not os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
    load_dotenv()

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Timezone
jst = pytz.timezone('Asia/Tokyo')

# Pattern constants
PATTERN_YYYY_MM_DD_HH = "%Y-%m-%d %H"  # ← SPACE between date and hour!
PATTERN_YYYYMM = "%Y%m"
CHUNK_INDEX_TRACKING_DATA_KEY = ":chunk"
DELIMITER = ";-;"

# Domain type classification
ORGANIC_PAGES = [
    "www.google.",
    "search.yahoo.co.jp",
    "www.bing.com"
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
    "b.hatena.ne.jp"
]

# Redis cache keys
CACHE_KEY_PREFIX = "heatmap:cache:"
CACHE_DOMAIN = f"{CACHE_KEY_PREFIX}domain"
CACHE_UTM_SOURCE = f"{CACHE_KEY_PREFIX}utm_source"
CACHE_UTM_MEDIUM = f"{CACHE_KEY_PREFIX}utm_medium"

# Global variables
redis_client = None
db_connection = None


class ReferrerDomainType(Enum):
    """Domain type enumeration"""
    NONE = 0
    ORGANIC = 1
    SOCIAL = 2


class CacheType(Enum):
    """Cache type enumeration"""
    DOMAIN = "domain"
    UTM_SOURCE = "utm_source"
    UTM_MEDIUM = "utm_medium"


def lambda_handler(event=None, context=None):
    """
    Lambda handler function
    Triggered by EventBridge schedule to move data from Redis to MySQL
    """
    logger.info("********************START MOVE DATA TO MYSQL********************")
    
    global redis_client, db_connection
    cnx = None
    region = get_region()

    try:
        # Get secret from AWS Secrets Manager
        secret = run_step("get_secret", get_secret, region)
        
        # Initialize database connection
        cnx = run_step("get_db_connection", get_db_connection, secret)
        
        # Initialize Redis connection
        run_step("init_redis_connection", init_redis_connection)
        
        # Execute main logic
        stats = run_step("execute_move_data", execute_move_data, cnx)
        
        # Commit transaction
        if cnx:
            cnx.commit()
            
        logger.info("********************END MOVE DATA TO MYSQL********************")

        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": "Move data from Redis to MySQL successfully",
                "stats": stats
            })
        }

    except Exception as e:
        if cnx:
            cnx.rollback()
        logger.error(f"Error in lambda_handler: {str(e)}", exc_info=True)
        raise

    finally:
        if cnx:
            cnx.close()
        if redis_client:
            redis_client.close()


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
    """Establish database connection with SSL"""
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


def get_secret(region):
    """Fetch database credentials from AWS Secrets Manager"""
    secret_name = os.environ.get('RDS_SECRET_NAME', 'rds/db-test-private')

    from botocore.config import Config
    config = Config(
        connect_timeout=5,
        read_timeout=10,
        retries={'max_attempts': 3}
    )

    logger.info("Creating boto3 client for Secrets Manager...")
    client = boto3.client('secretsmanager', region_name=region, config=config)

    logger.info("Fetching secret value from Secrets Manager...")
    response = client.get_secret_value(SecretId=secret_name)

    return json.loads(response['SecretString'])


def get_region() -> str:
    """Get AWS region from environment"""
    region_name = os.environ.get('AWS_REGION', 'ap-northeast-1')
    return region_name


def run_step(step_name: str, func, *args, **kwargs):
    """Execute a step with logging"""
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


def init_redis_connection():
    """Initialize Redis connection"""
    global redis_client
    
    try:
        redis_host = os.environ.get('REDIS_HOST')
        redis_port = int(os.environ.get('REDIS_PORT', 6379))
        redis_password = os.environ.get('REDIS_PASSWORD', '')
        
        logger.info(f"Connecting to Redis at {redis_host}:{redis_port}...")
        
        redis_client = redis.Redis(
            host=redis_host,
            port=redis_port,
            password=redis_password if redis_password else None,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            db=1
        )
        
        # Test connection
        redis_client.ping()
        logger.info("Redis connection established")
        
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {str(e)}")
        raise


def execute_move_data(connection) -> Dict[str, Any]:
    """Main logic to move data from Redis to MySQL"""
    try:
        # Calculate date key for 1 hour ago
        current_date_jst = datetime.now(jst)
        one_hour_ago = current_date_jst - timedelta(hours=1)
        date_key = one_hour_ago.strftime(PATTERN_YYYY_MM_DD_HH)
        table_name = one_hour_ago.strftime(PATTERN_YYYYMM)
        
        logger.info(f"**********(Move): Key data move to mysql: {date_key}")
        logger.info(f"**********(Move): Table name: {table_name}")
        
        # Get all keys matching pattern
        pattern = f"*{date_key}*"
        all_keys = get_redis_keys(pattern)
        
        if not all_keys:
            logger.info("No keys found to process")
            return {
                'date_key': date_key,
                'table_name': table_name,
                'total_keys': 0,
                'successful': 0,
                'failed': 0
            }
        
        # Filter out chunk index keys
        filtered_keys = filter_out_chunk_index_keys(all_keys)
        logger.info(f"**********(Move): Number key will be move to mysql: {len(filtered_keys)}")
        
        # Get active site schemas
        schema_map = get_list_schema_name(connection)
        logger.info(f"**********(Move): Number site now running: {len(schema_map)}")
        
        # Process keys in parallel
        stats = process_keys_parallel(connection, filtered_keys, schema_map, table_name)
        
        return {
            'date_key': date_key,
            'table_name': table_name,
            'total_keys': len(filtered_keys),
            'successful': stats['successful'],
            'failed': stats['failed']
        }
        
    except Exception as e:
        logger.error(f"Error in execute_move_data: {str(e)}", exc_info=True)
        raise


def get_redis_keys(pattern: str) -> List[str]:
    """Get all Redis keys matching pattern"""
    try:
        keys = redis_client.keys(pattern)
        logger.info(f"Found {len(keys)} keys matching pattern: {pattern}")
        return keys
    except Exception as e:
        logger.error(f"Error getting keys with pattern {pattern}: {str(e)}")
        return []


def filter_out_chunk_index_keys(keys: List[str]) -> List[str]:
    """Filter out chunk index tracking keys"""
    filtered = [key for key in keys if CHUNK_INDEX_TRACKING_DATA_KEY not in key]
    logger.info(f"Filtered {len(keys) - len(filtered)} chunk index keys")
    return filtered


def get_list_schema_name(connection) -> Dict[str, int]:
    """
    Get all database schemas
    Java: SELECT SCHEMA_NAME FROM INFORMATION_SCHEMA.SCHEMATA
    This gets ALL database schemas in MySQL, not just active sites in HEATMAP_SITE
    """
    try:
        with connection.cursor() as cursor:
            # This matches Java's getListSchemaName() method exactly
            query = """
                SELECT SCHEMA_NAME 
                FROM INFORMATION_SCHEMA.SCHEMATA
            """
            cursor.execute(query)
            results = cursor.fetchall()
            
            # Create map with schema name as key, 1 as value (matching Java HashMap structure)
            schema_map = {row['SCHEMA_NAME']: 1 for row in results}
            logger.info(f"Retrieved {len(schema_map)} database schemas from INFORMATION_SCHEMA")
            return schema_map
            
    except Exception as e:
        logger.error(f"Error getting schema names: {str(e)}")
        raise


def process_keys_parallel(connection, keys: List[str], schema_map: Dict[str, int], table_name: str) -> Dict[str, int]:
    """Process keys in parallel using ThreadPoolExecutor"""
    max_workers = int(os.environ.get('MAX_WORKERS', 6))
    
    successful_keys = 0
    failed_keys = 0
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        
        for key in keys:
            # Parse key format: siteId_timestamp_type:data
            parts = key.split('_')
            if len(parts) < 3:
                logger.warning(f"Invalid key format: {key}")
                continue
            
            site_id = parts[0]
            type_data = parts[2].split(':')[0]
            
            # Check if site exists in schema map
            if site_id not in schema_map:
                logger.info(f"**********(Move): Site not exists database: {site_id}")
                delete_redis_key(key)
                continue
            
            # Submit task for processing
            future = executor.submit(
                process_single_key,
                connection, key, site_id, type_data, table_name
            )
            futures[future] = key
        
        # Wait for all tasks to complete
        for future in as_completed(futures):
            key = futures[future]
            try:
                result = future.result()
                if result:
                    successful_keys += 1
                else:
                    failed_keys += 1
            except Exception as e:
                logger.error(f"Error processing key {key}: {str(e)}")
                failed_keys += 1
    
    logger.info(f"Processing completed - Success: {successful_keys}, Failed: {failed_keys}")
    
    return {
        'successful': successful_keys,
        'failed': failed_keys
    }


def process_single_key(connection, redis_key: str, site_id: str, type_key: str, table_name: str) -> bool:
    """Process a single Redis key based on type"""
    try:
        # Check if schema exists
        if not check_schema_exist(connection, site_id):
            logger.info(f"Schema not exist for site {site_id}, deleting key {redis_key}")
            delete_redis_key(redis_key)
            return False
        
        # Process based on type
        if type_key == 'v':
            return process_pageview(connection, redis_key, site_id, table_name)
        elif type_key == 'c':
            return process_click(connection, redis_key, site_id, table_name)
        elif type_key == 's':
            return process_scroll(connection, redis_key, site_id, table_name)
        elif type_key == 'r':
            return process_read(connection, redis_key, site_id, table_name)
        else:
            logger.warning(f"Unknown type key: {type_key}")
            return False
            
    except Exception as e:
        logger.error(f"Error processing key {redis_key}: {str(e)}")
        return False


def check_schema_exist(connection, site_id: str) -> bool:
    """
    Check if database schema exists for site
    Java: SELECT SCHEMA_NAME FROM INFORMATION_SCHEMA.SCHEMATA WHERE SCHEMA_NAME = ?
    """
    try:
        with connection.cursor() as cursor:
            query = """
                SELECT SCHEMA_NAME 
                FROM INFORMATION_SCHEMA.SCHEMATA 
                WHERE SCHEMA_NAME = %s
            """
            cursor.execute(query, (site_id,))
            result = cursor.fetchone()
            return result is not None
    except Exception as e:
        logger.error(f"Error checking schema for site {site_id}: {str(e)}")
        return False


def get_redis_set_data(key: str) -> Set[str]:
    """Get data from Redis Set"""
    try:
        data = redis_client.smembers(key)
        return data if data else set()
    except Exception as e:
        logger.error(f"Error getting set data for key {key}: {str(e)}")
        return set()


def delete_redis_key(key: str) -> bool:
    """Delete key from Redis"""
    try:
        redis_client.delete(key)
        logger.debug(f"Deleted Redis key: {key}")
        return True
    except Exception as e:
        logger.error(f"Error deleting key {key}: {str(e)}")
        return False


# ============================================================================
# DOMAIN / UTM CACHING FUNCTIONS
# ============================================================================

def resolve_domain_type(domain: str) -> ReferrerDomainType:
    """Resolve domain type (ORGANIC, SOCIAL, or NONE)"""
    if not domain:
        return ReferrerDomainType.NONE
    
    # Check if organic
    for organic_page in ORGANIC_PAGES:
        if organic_page in domain:
            return ReferrerDomainType.ORGANIC
    
    # Check if social
    for social_page in SOCIAL_PAGES:
        if social_page in domain:
            return ReferrerDomainType.SOCIAL
    
    return ReferrerDomainType.NONE


def get_cache_key(cache_type: CacheType) -> str:
    """Get Redis cache key based on cache type"""
    if cache_type == CacheType.DOMAIN:
        return CACHE_DOMAIN
    elif cache_type == CacheType.UTM_SOURCE:
        return CACHE_UTM_SOURCE
    elif cache_type == CacheType.UTM_MEDIUM:
        return CACHE_UTM_MEDIUM
    else:
        raise ValueError(f"Unsupported cache type: {cache_type}")


def get_from_redis_cache(cache_key: str, value: str) -> Optional[int]:
    """Get ID from Redis hash map cache"""
    try:
        cached_value = redis_client.hget(cache_key, value)
        if cached_value:
            return int(cached_value)
        return None
    except Exception as e:
        logger.error(f"Error getting from Redis cache [{cache_key}][{value}]: {str(e)}")
        return None


def set_to_redis_cache(cache_key: str, value: str, id_value: int):
    """Set ID to Redis hash map cache"""
    try:
        redis_client.hset(cache_key, value, str(id_value))
    except Exception as e:
        logger.error(f"Error setting to Redis cache [{cache_key}][{value}]: {str(e)}")


def get_id_cached(connection, cache_type: CacheType, value: str) -> Optional[int]:
    """
    Get or create ID for referrer domain, UTM source, or UTM medium with Redis caching
    
    Steps:
    1. Check Redis cache
    2. If cache miss, get/create from database
    3. Store in Redis cache
    """
    try:
        if not value:
            return None
        
        # Get cache key
        cache_key = get_cache_key(cache_type)
        
        # Step 1: Check Redis cache
        cached_id = get_from_redis_cache(cache_key, value)
        if cached_id is not None:
            return cached_id
        
        # Step 2: Cache miss - get/create from database
        db_id = save_value_to_database(connection, cache_type, value)
        
        # Step 3: Store in Redis cache
        if db_id is not None:
            set_to_redis_cache(cache_key, value, db_id)
        
        return db_id
        
    except Exception as e:
        logger.error(f"Cannot get data cache [Type={cache_type.value}] [Value={value}]: {str(e)}")
        raise


def save_value_to_database(connection, cache_type: CacheType, value: str) -> Optional[int]:
    """Save value to database based on cache type"""
    if cache_type == CacheType.DOMAIN:
        return save_referrer_domain(connection, value)
    elif cache_type == CacheType.UTM_SOURCE:
        return save_utm_source(connection, value)
    elif cache_type == CacheType.UTM_MEDIUM:
        return save_utm_medium(connection, value)
    else:
        raise ValueError(f"Unsupported cache type: {cache_type}")


def get_referrer_domain_id(connection, domain: str) -> Optional[int]:
    """Get or create referrer domain ID with caching"""
    return get_id_cached(connection, CacheType.DOMAIN, domain)


def get_utm_source_id(connection, utm_source: str) -> Optional[int]:
    """Get or create UTM source ID with caching"""
    return get_id_cached(connection, CacheType.UTM_SOURCE, utm_source)


def get_utm_medium_id(connection, utm_medium: str) -> Optional[int]:
    """Get or create UTM medium ID with caching"""
    return get_id_cached(connection, CacheType.UTM_MEDIUM, utm_medium)


def save_referrer_domain(connection, domain: str) -> Optional[int]:
    """
    Save referrer domain with type classification
    """
    try:
        # Resolve domain type
        domain_type = resolve_domain_type(domain)
        
        with connection.cursor() as cursor:
            sql = """
                INSERT INTO `REFERRER_DOMAIN` (DOMAIN, TYPE) 
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE id = LAST_INSERT_ID(id)
            """
            # Java: ps.setString(2, type.name()) → stores "ORGANIC", "SOCIAL", "NONE"
            cursor.execute(sql, (domain, domain_type.name))
            
            # Get the ID (either newly inserted or existing)
            return cursor.lastrowid if cursor.lastrowid else cursor.fetchone()['id']
            
    except Exception as e:
        logger.error(f"Error saving referrer domain {domain}: {str(e)}")
        return None


def save_utm_source(connection, utm_source: str) -> Optional[int]:
    """
    Save UTM source
    
    """
    try:
        with connection.cursor() as cursor:
            sql = """
                INSERT INTO `REFERRER_UTM_SOURCE` (UTM_SOURCE) 
                VALUES (%s)
                ON DUPLICATE KEY UPDATE id = LAST_INSERT_ID(id)
            """
            cursor.execute(sql, (utm_source,))
            return cursor.lastrowid
            
    except Exception as e:
        logger.error(f"Error saving UTM source {utm_source}: {str(e)}")
        return None


def save_utm_medium(connection, utm_medium: str) -> Optional[int]:
    """
    Save UTM medium
    
    """
    try:
        with connection.cursor() as cursor:
            sql = """
                INSERT INTO `REFERRER_UTM_MEDIUM` (UTM_MEDIUM) 
                VALUES (%s)
                ON DUPLICATE KEY UPDATE id = LAST_INSERT_ID(id)
            """
            cursor.execute(sql, (utm_medium,))
            return cursor.lastrowid
            
    except Exception as e:
        logger.error(f"Error saving UTM medium {utm_medium}: {str(e)}")
        return None


def extract_and_create_parameter_pairs(parameters_str: str) -> List[Dict]:
    """
    Extract UTM parameters and create parameter pair objects
    
    ✅ NEW FUNCTION: Matching Java's parameter pair extraction logic
    """
    if not parameters_str:
        return []
    
    parameter_pairs = []
    
    try:
        # Split by & to get individual parameters
        param_pairs = parameters_str.split('&')
        
        for pair in param_pairs:
            if '=' in pair:
                parts = pair.split('=', 1)
                
                # ✅ URL decode (matching Java's decodeUnicodeEscapeSequence)
                try:
                    key = unquote(parts[0], encoding='utf-8', errors='replace')
                    value = unquote(parts[1], encoding='utf-8', errors='replace') if len(parts) > 1 else ""
                except Exception:
                    key = parts[0]
                    value = parts[1] if len(parts) > 1 else ""
                
                # Java FilterRule.accept() REMOVES utm_ parameters, keeps everything else
                if not key.startswith('utm_'):
                    # Matching Java's ParameterPair.joinPair(): StringUtils.join(key, value)
                    pair_id = hashlib.md5(f"{key}{value}".encode()).hexdigest()
                    
                    parameter_pairs.append({
                        'id': pair_id,
                        'key': key,
                        'value': value
                    })
        
        return parameter_pairs
        
    except Exception as e:
        logger.error(f"Error extracting parameter pairs: {str(e)}")
        return []


def save_parameter_pairs(connection, parameter_pairs: List[Dict]) -> bool:
    """
    Save parameter pairs to database
    
    Saves to BOTH PARAMETER_PAIR_GROUP and PARAMETER_PAIR tables
    """
    if not parameter_pairs:
        return True
    
    retry_count = 0
    remaining_pairs = parameter_pairs.copy()
    
    while retry_count <= 3:
        try:
            # Create a group ID for this set of parameters
            sorted_pairs = sorted(remaining_pairs, key=lambda x: x['key'])
            
            # Java: parameterPairs.stream().map(ParameterPair::joinPair).collect(Collectors.joining())
            # joinPair() returns StringUtils.join(key, value) = key + value (no separator)
            joined_str = ''.join([f"{p['key']}{p['value']}" for p in sorted_pairs])
            group_id = hashlib.md5(joined_str.encode()).hexdigest()
            
            with connection.cursor() as cursor:
                for pair in remaining_pairs:
                    sql_group = """
                        INSERT INTO PARAMETER_PAIR_GROUP (ID, PARAMETER_PAIR_ID) 
                        VALUES (%s, %s)
                        ON DUPLICATE KEY UPDATE ID = ID
                    """
                    cursor.execute(sql_group, (group_id, pair['id']))
                
                # ✅ FIXED: Save to PARAMETER_PAIR table (UPPERCASE)
                for pair in remaining_pairs:
                    sql_pair = """
                        INSERT INTO PARAMETER_PAIR (ID, `KEY`, `VALUE`) 
                        VALUES (%s, %s, %s)
                        ON DUPLICATE KEY UPDATE `KEY` = `KEY`, `VALUE` = `VALUE`
                    """
                    cursor.execute(sql_pair, (pair['id'], pair['key'], pair['value']))
            
            # Success - break out of retry loop
            return True
            
        except pymysql.err.OperationalError as e:
            error_code = e.args[0] if e.args else None
            if error_code == 1213:  # MySQL deadlock error
                retry_count += 1
                if retry_count > 3:
                    logger.error(f"Deadlock retry limit exceeded for parameter pairs after {retry_count} attempts")
                    return False
                
                logger.warning(f"Deadlock detected, retrying ({retry_count}/3)...")
                # Continue to next retry with remaining pairs
                continue
            else:
                # Other operational error - fail immediately
                logger.error(f"Operational error saving parameter pairs: {str(e)}")
                return False
                
        except Exception as e:
            logger.error(f"Error saving parameter pairs: {str(e)}")
            return False
    
    # Exhausted retries
    return False


# ============================================================================
# DATA PARSING FUNCTIONS
# ============================================================================

def parse_pageview_data(raw_data: Set[str], connection) -> tuple[List[Dict], List[Dict]]:
    """
    Parse pageview data from Redis set with caching for domain/UTM IDs
    Format: dateCreate;-;referrerId;-;url;-;urlId;-;device;-;winWidth;-;ipA;-;userAgent;-;parameters;-;domain;-;utmSource;-;utmMedium
    
    Returns: (parsed_pageviews, all_parameter_pairs)
    """
    parsed_list = []
    all_parameter_pairs = []
    
    # In-memory cache for this batch
    domain_id_cache = {}
    utm_source_id_cache = {}
    utm_medium_id_cache = {}
    
    for row in raw_data:
        try:
            parts = row.split(DELIMITER)
            if len(parts) < 3:
                continue
            
            # Extract parameters
            parameters_str = parts[8] if len(parts) > 8 else None
            
            # ✅ NEW: Extract and create parameter pairs (matching Java logic)
            parameter_pairs = extract_and_create_parameter_pairs(parameters_str) if parameters_str else []
            
            # Create group ID for this record's parameters
            parameter_pair_group_id = None
            if parameter_pairs:
                sorted_pairs = sorted(parameter_pairs, key=lambda x: x['key'])
                joined_str = ''.join([f"{p['key']}{p['value']}" for p in sorted_pairs])
                parameter_pair_group_id = hashlib.md5(joined_str.encode()).hexdigest()
                all_parameter_pairs.extend(parameter_pairs)
            
            dto = {
                'dateCreate': parts[0] if len(parts) > 0 else None,
                'referrerId': parts[1] if len(parts) > 1 else None,
                'url': parts[2] if len(parts) > 2 else None,
                'urlId': parts[3] if len(parts) > 3 else None,
                'device': parts[4] if len(parts) > 4 else None,
                'winWidth': parts[5] if len(parts) > 5 else '0',
                'ipA': parts[6] if len(parts) > 6 and parts[6] and len(parts[6]) < 50 else '0.0.0.0',
                'userAgent': parts[7] if len(parts) > 7 else 'na',
                'parameterPairGroupId': parameter_pair_group_id,
            }
            
            # Get domain ID with Redis + in-memory caching
            if len(parts) > 9 and parts[9] and parts[9].strip():
                domain = parts[9]
                if domain not in domain_id_cache:
                    domain_id_cache[domain] = get_referrer_domain_id(connection, domain)
                dto['refDomainId'] = domain_id_cache[domain]
            
            # Get UTM source ID
            if len(parts) > 10 and parts[10] and parts[10].strip():
                utm_source = parts[10]
                if utm_source not in utm_source_id_cache:
                    utm_source_id_cache[utm_source] = get_utm_source_id(connection, utm_source)
                dto['refUtmSourceId'] = utm_source_id_cache[utm_source]
            
            # Get UTM medium ID
            if len(parts) > 11 and parts[11] and parts[11].strip():
                utm_medium = parts[11]
                if utm_medium not in utm_medium_id_cache:
                    utm_medium_id_cache[utm_medium] = get_utm_medium_id(connection, utm_medium)
                dto['refUtmMediumId'] = utm_medium_id_cache[utm_medium]
            
            parsed_list.append(dto)
            
        except Exception as e:
            logger.error(f"Error parsing pageview row: {str(e)}")
            continue
    
    return parsed_list, all_parameter_pairs


def parse_click_data(raw_data: Set[str]) -> List[Dict]:
    """Parse click data from Redis set"""
    parsed_list = []
    
    for row in raw_data:
        try:
            parts = row.split(DELIMITER)
            if len(parts) < 11:
                continue
            
            dto = {
                'dateCreate': parts[0],
                'device': parts[1],
                'winWidth': parts[2],
                'docWidth': parts[3],
                'docHeight': parts[4],
                'referrerId': parts[5],
                'xpos': parts[6],
                'ypos': parts[7],
                'link': parts[8],
                'title': parts[9],
                'urlId': parts[10],
            }
            
            parsed_list.append(dto)
            
        except Exception as e:
            logger.error(f"Error parsing click row: {str(e)}")
            continue
    
    return parsed_list


def parse_scroll_data(raw_data: Set[str]) -> List[Dict]:
    """Parse scroll data from Redis set"""
    parsed_list = []
    
    for row in raw_data:
        try:
            parts = row.split(DELIMITER)
            if len(parts) < 7:
                continue
            
            dto = {
                'dateCreate': parts[0],
                'device': parts[1],
                'winWidth': parts[2],
                'docHeight': parts[3],
                'referrerId': parts[4],
                'pos': parts[5],
                'urlId': parts[6],
            }
            
            parsed_list.append(dto)
            
        except Exception as e:
            logger.error(f"Error parsing scroll row: {str(e)}")
            continue
    
    return parsed_list


def parse_read_data(raw_data: Set[str]) -> List[Dict]:
    """Parse read data from Redis set"""
    parsed_list = []
    
    for row in raw_data:
        try:
            parts = row.split(DELIMITER)
            if len(parts) < 8:
                continue
            
            dto = {
                'dateCreate': parts[0],
                'device': parts[1],
                'winWidth': parts[2],
                'winHeight': parts[3],
                'docHeight': parts[4],
                'referrerId': parts[5],
                'pos': parts[6],
                'urlId': parts[7],
            }
            
            parsed_list.append(dto)
            
        except Exception as e:
            logger.error(f"Error parsing read row: {str(e)}")
            continue
    
    return parsed_list


# ============================================================================
# DATA PROCESSING FUNCTIONS
# ============================================================================

def process_pageview(connection, redis_key: str, site_id: str, table_name: str) -> bool:
    """
    Process pageview data
    """
    try:
        # Get raw data from Redis Set
        raw_data = get_redis_set_data(redis_key)
        
        if not raw_data:
            delete_redis_key(redis_key)
            return True
        
        # Parse data - now returns parameter pairs too
        parsed_data, parameter_pairs = parse_pageview_data(raw_data, connection)
        
        if not parsed_data:
            delete_redis_key(redis_key)
            return True
        
        # Add to MySQL
        is_success = add_page_view(connection, site_id, parsed_data, table_name)
        
        if not is_success:
            return False
        
        # Store total PV count
        try:
            pv_stored = store_total_pv(connection, site_id, table_name, len(parsed_data))
            if not pv_stored:
                logger.warning(f"**********(MoveRunable): Can not store total PV: {site_id}-[{table_name}]")
        except Exception as e:
            logger.error(f"**********(MoveRunable): Can not store total PV of {site_id}-[{table_name}]: {str(e)}")
        
        if parameter_pairs:
            try:
                # Remove duplicates based on ID
                unique_pairs = {p['id']: p for p in parameter_pairs}.values()
                param_success = save_parameter_pairs(connection, list(unique_pairs))
                if not param_success:
                    logger.warning(f"*** Can not add parameter with siteId = {site_id}")
                is_success = is_success and param_success
            except Exception as e:
                logger.error(f"*** Can not add parameter with siteId = {site_id}: {str(e)}")
                is_success = False
        
        # "In case any process not success, we will import cache data again on next hour"
        if is_success:
            delete_redis_key(redis_key)
        
        return is_success
        
    except Exception as e:
        logger.error(f"Error processing pageview for key {redis_key}: {str(e)}")
        return False


def process_click(connection, redis_key: str, site_id: str, table_name: str) -> bool:
    """Process click data"""
    try:
        raw_data = get_redis_set_data(redis_key)
        
        if not raw_data:
            delete_redis_key(redis_key)
            return True
        
        parsed_data = parse_click_data(raw_data)
        
        if not parsed_data:
            delete_redis_key(redis_key)
            return True
        
        is_success = add_click(connection, site_id, parsed_data, table_name)
        
        if is_success:
            delete_redis_key(redis_key)
        
        return is_success
        
    except Exception as e:
        logger.error(f"Error processing click for key {redis_key}: {str(e)}")
        return False


def process_scroll(connection, redis_key: str, site_id: str, table_name: str) -> bool:
    """Process scroll data"""
    try:
        raw_data = get_redis_set_data(redis_key)
        
        if not raw_data:
            delete_redis_key(redis_key)
            return True
        
        parsed_data = parse_scroll_data(raw_data)
        
        if not parsed_data:
            delete_redis_key(redis_key)
            return True
        
        is_success = add_scroll(connection, site_id, parsed_data, table_name)
        
        if is_success:
            delete_redis_key(redis_key)
        
        return is_success
        
    except Exception as e:
        logger.error(f"Error processing scroll for key {redis_key}: {str(e)}")
        return False


def process_read(connection, redis_key: str, site_id: str, table_name: str) -> bool:
    """Process read data"""
    try:
        raw_data = get_redis_set_data(redis_key)
        
        if not raw_data:
            delete_redis_key(redis_key)
            return True
        
        parsed_data = parse_read_data(raw_data)
        
        if not parsed_data:
            delete_redis_key(redis_key)
            return True
        
        is_success = add_read(connection, site_id, parsed_data, table_name)
        
        if is_success:
            delete_redis_key(redis_key)
        
        return is_success
        
    except Exception as e:
        logger.error(f"Error processing read for key {redis_key}: {str(e)}")
        return False


# ============================================================================
# DATABASE INSERT FUNCTIONS
# ============================================================================

def add_page_view(connection, site_id: str, data_list: List[Dict], table_name: str) -> bool:
    """
    Insert pageview data to MySQL
    """
    if not data_list:
        return True
        
    try:
        connection.autocommit(False)
        
        with connection.cursor() as cursor:
            table = f"{site_id}.{table_name}_referrer"
            
            sql = f"""
                INSERT INTO {table} 
                (date_added, referrer_id, url, url_id, ref_domain_id, ref_utm_source_id, 
                 ref_utm_medium_id, parameter_pair_group_id, device, win_width, ipa, user_agent)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            
            batch_size = 500
            
            for i, item in enumerate(data_list, 1):
                # Truncate user_agent to 499 chars
                user_agent = item.get('userAgent', 'na')
                if len(user_agent) > 500:
                    user_agent = user_agent[:499]
                
                values = (
                    item.get('dateCreate'),
                    item.get('referrerId'),
                    item.get('url'),
                    item.get('urlId'),
                    item.get('refDomainId'),
                    item.get('refUtmSourceId'),
                    item.get('refUtmMediumId'),
                    item.get('parameterPairGroupId'),
                    item.get('device'),
                    item.get('winWidth'),
                    item.get('ipA'),
                    user_agent
                )
                
                cursor.execute(sql, values)
                
                if i % batch_size == 0 or i == len(data_list):
                    connection.commit()
            
            logger.info(f"Inserted {len(data_list)} pageview records for site {site_id}")
            connection.autocommit(True)
            return True
            
    except Exception as e:
        logger.error(f"Error adding pageview for site {site_id}: {str(e)}")
        connection.rollback()
        connection.autocommit(True)
        return False


def add_click(connection, site_id: str, data_list: List[Dict], table_name: str) -> bool:
    """Insert click data to MySQL"""
    if not data_list:
        return True
        
    try:
        connection.autocommit(False)
        
        with connection.cursor() as cursor:
            table = f"{site_id}.{table_name}_click"
            
            sql = f"""
                INSERT INTO {table} 
                (date_added, device, win_width, doc_width, doc_height, referrer_id, 
                 x_pos, y_pos, link, title, url_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            
            batch_size = 500
            for i, item in enumerate(data_list, 1):
                values = (
                    item.get('dateCreate'),
                    item.get('device'),
                    item.get('winWidth'),
                    item.get('docWidth'),
                    item.get('docHeight'),
                    item.get('referrerId'),
                    item.get('xpos'),
                    item.get('ypos'),
                    item.get('link'),
                    item.get('title'),
                    item.get('urlId')
                )
                
                cursor.execute(sql, values)
                
                if i % batch_size == 0 or i == len(data_list):
                    connection.commit()
            
            logger.info(f"Inserted {len(data_list)} click records for site {site_id}")
            connection.autocommit(True)
            return True
            
    except Exception as e:
        logger.error(f"Error adding click for site {site_id}: {str(e)}")
        connection.rollback()
        connection.autocommit(True)
        return False


def add_scroll(connection, site_id: str, data_list: List[Dict], table_name: str) -> bool:
    """Insert scroll data to MySQL"""
    if not data_list:
        return True
        
    try:
        connection.autocommit(False)
        
        with connection.cursor() as cursor:
            table = f"{site_id}.{table_name}_scroll"
            
            sql = f"""
                INSERT INTO {table} 
                (date_added, device, win_width, doc_height, referrer_id, pos, url_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """
            
            batch_size = 500
            for i, item in enumerate(data_list, 1):
                values = (
                    item.get('dateCreate'),
                    item.get('device'),
                    item.get('winWidth'),
                    item.get('docHeight'),
                    item.get('referrerId'),
                    item.get('pos'),
                    item.get('urlId')
                )
                
                cursor.execute(sql, values)
                
                if i % batch_size == 0 or i == len(data_list):
                    connection.commit()
            
            logger.info(f"Inserted {len(data_list)} scroll records for site {site_id}")
            connection.autocommit(True)
            return True
            
    except Exception as e:
        logger.error(f"Error adding scroll for site {site_id}: {str(e)}")
        connection.rollback()
        connection.autocommit(True)
        return False


def add_read(connection, site_id: str, data_list: List[Dict], table_name: str) -> bool:
    """Insert read data to MySQL"""
    if not data_list:
        return True
        
    try:
        connection.autocommit(False)
        
        with connection.cursor() as cursor:
            table = f"{site_id}.{table_name}_read"
            
            sql = f"""
                INSERT INTO {table} 
                (date_added, device, win_width, win_height, doc_height, referrer_id, pos, url_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """
            
            batch_size = 500
            for i, item in enumerate(data_list, 1):
                values = (
                    item.get('dateCreate'),
                    item.get('device'),
                    item.get('winWidth'),
                    item.get('winHeight'),
                    item.get('docHeight'),
                    item.get('referrerId'),
                    item.get('pos'),
                    item.get('urlId')
                )
                
                cursor.execute(sql, values)
                
                if i % batch_size == 0 or i == len(data_list):
                    connection.commit()
            
            logger.info(f"Inserted {len(data_list)} read records for site {site_id}")
            connection.autocommit(True)
            return True
            
    except Exception as e:
        logger.error(f"Error adding read for site {site_id}: {str(e)}")
        connection.rollback()
        connection.autocommit(True)
        return False


def store_total_pv(connection, site_id: str, table_name: str, count: int) -> bool:
    """Store total pageview count in tracked_pv table"""
    try:
        with connection.cursor() as cursor:
            sql = """
                INSERT INTO HEAT_MAP.tracked_pv (site_id, table_name, total_pv, created_at)
                VALUES (%s, %s, %s, NOW())
                ON DUPLICATE KEY UPDATE 
                total_pv = total_pv + VALUES(total_pv),
                updated_at = NOW()
            """
            cursor.execute(sql, (site_id, table_name, count))
            logger.info(f"Stored total PV: {count} for site {site_id}, table {table_name}")
            return True
            
    except Exception as e:
        logger.error(f"**********(MoveRunable): Can not store total PV of {site_id}-[{table_name}]: {str(e)}")
        return False


if __name__ == "__main__":
    # For local testing
    lambda_handler()