import json
import logging
import pymysql
import ssl
import os
import boto3
import redis
from datetime import datetime
from typing import Dict, Any, Optional
from dotenv import load_dotenv

# Load environment variables from .env file only when running locally.
# In AWS Lambda, environment variables should be configured via the console or IaC.
if not os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
    load_dotenv()

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event=None, context=None):
    """
    Main Lambda handler for moving data to MySQL.
    Connects to both RDS MySQL and Redis Valkey to perform data operations.
    """
    mysql_conn = None
    redis_conn = None
    cursor = None
    region = get_region()

    try:
        logger.info("Lambda function started - Move Data to MySQL")

        # Get database credentials from Secrets Manager
        secret = run_step("get_secret", get_secret, region)

        # Connect to MySQL RDS
        mysql_conn = run_step("get_mysql_connection", get_mysql_connection, secret)
        cursor = mysql_conn.cursor()

        # Connect to Redis Valkey
        redis_conn = run_step("get_redis_connection", get_redis_connection)

        # Process data transfer (example logic)
        run_step("process_data_transfer", process_data_transfer, mysql_conn, redis_conn, event)

        logger.info("Lambda function completed successfully")
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Data transfer completed successfully',
                'timestamp': datetime.utcnow().isoformat()
            })
        }

    except Exception as e:
        logger.error(f"Error in lambda_handler: {str(e)}", exc_info=True)
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e),
                'timestamp': datetime.utcnow().isoformat()
            })
        }
    finally:
        # Close connections
        if cursor:
            cursor.close()
        if mysql_conn:
            mysql_conn.close()
        if redis_conn:
            redis_conn.close()
        logger.info("Connections closed")


def run_step(step_name: str, func, *args, **kwargs):
    """Execute a function step with logging"""
    logger.info(f"Starting step: {step_name}")
    try:
        result = func(*args, **kwargs)
        logger.info(f"Completed step: {step_name}")
        return result
    except Exception as e:
        logger.error(f"Error in step {step_name}: {str(e)}", exc_info=True)
        raise


def get_region() -> str:
    """Get AWS region"""
    region = os.getenv("AWS_REGION", "ap-northeast-1")
    logger.info(f"AWS Region: {region}")
    return region


def get_secret(region: str) -> Dict[str, Any]:
    """
    Retrieve database credentials from AWS Secrets Manager
    """
    secret_name = os.getenv("RDS_SECRET_NAME", "rds/db-test-private")
    logger.info(f"Retrieving secret: {secret_name}")

    session = boto3.session.Session()
    client = session.client(
        service_name='secretsmanager',
        region_name=region
    )

    try:
        get_secret_value_response = client.get_secret_value(SecretId=secret_name)
        secret_string = get_secret_value_response['SecretString']
        secret = json.loads(secret_string)
        logger.info("Successfully retrieved secret from Secrets Manager")
        return secret
    except Exception as e:
        logger.error(f"Error retrieving secret: {str(e)}")
        raise


def get_mysql_connection(secret: Dict[str, Any]) -> pymysql.connections.Connection:
    """
    Establish connection to MySQL RDS
    """
    logger.info("Establishing MySQL connection")

    # SSL Configuration for RDS
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_REQUIRED

    # Try to load RDS CA bundle
    ca_bundle_path = os.getenv("RDS_CA_BUNDLE_PATH", "/var/task/rds-ca-bundle.pem")
    if os.path.exists(ca_bundle_path):
        ssl_context.load_verify_locations(ca_bundle_path)
        logger.info(f"Loaded RDS CA bundle from {ca_bundle_path}")
    else:
        logger.warning(f"RDS CA bundle not found at {ca_bundle_path}, using default SSL context")

    try:
        connection = pymysql.connect(
            host=secret['host'],
            port=int(secret.get('port', 3306)),
            user=secret['username'],
            password=secret['password'],
            database=secret.get('dbname', secret.get('database', 'mysql')),
            ssl=ssl_context,
            connect_timeout=10,
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )
        logger.info("Successfully connected to MySQL RDS")
        return connection
    except Exception as e:
        logger.error(f"Error connecting to MySQL: {str(e)}")
        raise


def get_redis_connection() -> redis.Redis:
    """
    Establish connection to Redis Valkey
    """
    logger.info("Establishing Redis Valkey connection")

    redis_host = os.getenv("REDIS_HOST", "localhost")
    redis_port = int(os.getenv("REDIS_PORT", 6379))
    redis_db = int(os.getenv("REDIS_DB", 0))
    redis_password = os.getenv("REDIS_PASSWORD", None)
    redis_ssl = os.getenv("REDIS_SSL", "false").lower() == "true"

    try:
        connection = redis.Redis(
            host=redis_host,
            port=redis_port,
            db=redis_db,
            password=redis_password,
            ssl=redis_ssl,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5
        )
        
        # Test connection
        connection.ping()
        logger.info(f"Successfully connected to Redis Valkey at {redis_host}:{redis_port}")
        return connection
    except Exception as e:
        logger.error(f"Error connecting to Redis Valkey: {str(e)}")
        raise


def process_data_transfer(
    mysql_conn: pymysql.connections.Connection,
    redis_conn: redis.Redis,
    event: Optional[Dict[str, Any]] = None
) -> None:
    """
    Process data transfer between Redis and MySQL.
    This is a template function - customize based on your specific use case.
    """
    logger.info("Starting data transfer process")
    
    cursor = mysql_conn.cursor()
    
    try:
        # Example 1: Read data from Redis and insert into MySQL
        # Get keys matching a pattern from Redis
        pattern = event.get('redis_key_pattern', '*') if event else '*'
        keys = redis_conn.keys(pattern)
        
        logger.info(f"Found {len(keys)} keys in Redis matching pattern: {pattern}")
        
        # Example: Transfer data from Redis to MySQL
        for key in keys[:10]:  # Limit to first 10 for demonstration
            value = redis_conn.get(key)
            if value:
                # Example: Insert into a staging table
                cursor.execute(
                    """
                    INSERT INTO data_staging (redis_key, redis_value, created_at)
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE 
                        redis_value = VALUES(redis_value),
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (key, value, datetime.utcnow())
                )
        
        mysql_conn.commit()
        logger.info("Data transfer completed successfully")
        
        # Example 2: Cache MySQL query results in Redis
        cursor.execute("SELECT COUNT(*) as total FROM data_staging")
        result = cursor.fetchone()
        if result:
            redis_conn.setex(
                'mysql:data_staging:count',
                3600,  # Expire after 1 hour
                result['total']
            )
            logger.info(f"Cached data_staging count in Redis: {result['total']}")
        
    except Exception as e:
        mysql_conn.rollback()
        logger.error(f"Error in data transfer process: {str(e)}")
        raise
    finally:
        cursor.close()


# For local testing
if __name__ == "__main__":
    # Test locally
    result = lambda_handler({}, None)
    print(json.dumps(result, indent=2))
