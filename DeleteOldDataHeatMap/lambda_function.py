import json
import logging
import pymysql
import ssl
import os
import boto3
from datetime import datetime
from dateutil.relativedelta import relativedelta
from typing import List, Dict, Any, Optional
import pytz
from dotenv import load_dotenv

# Load environment variables from .env file only when running locally.
# In AWS Lambda, environment variables should be configured via the console or IaC.
if not os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
    load_dotenv()

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# logging.basicConfig(
#     level=logging.INFO,
#     format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
# )
# logger = logging.getLogger(__name__)

jst = pytz.timezone('Asia/Tokyo')
current_date = datetime.now(jst)
datetime_format = "%Y-%m-%d %H:%M:%S"

def lambda_handler(event=None, context=None):
    logger.info("********************START DELETE OLD DATA********************")
    
    cnx = None
    region = get_region()

    try:
        secret = run_step("get_secret", get_secret, region)
        
        cnx = run_step("get_db_connection", get_db_connection, secret)
        
        run_step("auto_update_date_min_heatmap_site", auto_update_date_min_heatmap_site, cnx)
        
        if cnx:
            cnx.commit()
            
        logger.info("********************END DELETE OLD DATA********************")

        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": "Delete old data from HEATMAP successfully",
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


def get_secret(region):
    secret_name = os.environ.get('RDS_SECRET_NAME', 'rds/db-test-private')

    # Create client with timeout config
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
    region_name = os.environ.get('AWS_REGION', 'ap-northeast-1')
    return region_name


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


def calculate_retention_dates(retention_days: int, base_date: datetime = None) -> Optional[Dict[str, datetime]]:
    """
    Calculate threshold and new_date_min based on retention days.
    
    Args:
        retention_days: Number of days for retention (30 or 90)
        base_date: Base date for calculation (defaults to current_date)
    
    Returns:
        Dictionary with 'threshold' and 'new_date_min' datetime objects, or None if unsupported
    
    Logic:
    - 30 days retention: threshold=2 months ago, new_date_min=1 month ago
    - 90 days retention: threshold=4 months ago, new_date_min=3 months ago
    - Other values: return None (skip)
    """
    if base_date is None:
        base_date = current_date
    
    # Mapping: retention days -> (months to check, months for new date_min)
    retention_config = {
        30: {'check_months': 2, 'update_months': 1},
        90: {'check_months': 4, 'update_months': 3}
    }
    
    config = retention_config.get(retention_days)
    if not config:
        return None
    
    return {
        'threshold': base_date - relativedelta(months=config['check_months']),
        'new_date_min': (base_date - relativedelta(months=config['update_months'])).replace(day=1)
    }


def auto_update_date_min_heatmap_site(connection):
    """
    Automatically update date_min for heatmap sites to delete old data based on package retention limits.

    Logic:
    - 30 days retention: If data exists from 2 months ago or older, update date_min to 1 month ago
    - 90 days retention: If data exists from 4 months ago or older, update date_min to 3 months ago
    """
    try:
        # Get list of package limits
        package_limits = get_list_package_limit(connection)
        
        for package in package_limits:
            retention_days = package['TIME_DELETE_DATA']
            
            # Calculate dates using extracted function
            dates = calculate_retention_dates(retention_days)
            if dates is None:
                logger.warning(f"Skipping package {package['PACKAGE_CODE']}: Unsupported retention days {retention_days}")
                continue
            
            threshold = dates['threshold']
            new_date_min = dates['new_date_min']
            
            # Process sites for this package
            sites = get_list_heatmap_site_by_package_code(connection, package['PACKAGE_CODE'])
            
            for site in sites:
                try:
                    # Convert DATE_MIN to timezone-aware datetime
                    site_date_min = site['DATE_MIN']
                    if isinstance(site_date_min, str):
                        site_date_min = jst.localize(datetime.strptime(site_date_min, datetime_format))
                    elif site_date_min.tzinfo is None:
                        site_date_min = jst.localize(site_date_min)
                    
                    # Update if old enough
                    if site_date_min <= threshold:
                        new_date_min_str = new_date_min.strftime(datetime_format)
                        logger.info(f"Updating site {site['SITE_ID']}: {site['DATE_MIN']} -> {new_date_min_str}")
                        update_date_min(connection, site['SITE_ID'], new_date_min_str)
                
                except Exception as e:
                    logger.error(f"Error processing site {site.get('SITE_ID')}: {str(e)}")
                    continue
    
    except Exception as e:
        logger.error(f"Error in auto_update_date_min_heatmap_site: {str(e)}", exc_info=True)
        raise


def get_list_package_limit(connection) -> List[Dict[str, Any]]:
    """
    Get list of package limits from database
    """
    try:
        with connection.cursor() as cursor:
            query = """
                    SELECT HS.PACKAGE_CODE,
                           IF(LQ.TIME_DELETE_DATA IS NULL, 30, LQ.TIME_DELETE_DATA) AS TIME_DELETE_DATA
                    FROM HEAT_MAP.HEATMAP_SITE AS HS
                    LEFT JOIN HEAT_MAP.A_LIMIT_QUANTITY AS LQ
                    ON HS.PACKAGE_CODE = LQ.PACKAGE_CODE
                    WHERE HS.IS_DELETED = 0
                    GROUP BY HS.PACKAGE_CODE
                    HAVING TIME_DELETE_DATA IN (30, 90)
                    """
            cursor.execute(query)
            results = cursor.fetchall()
            logger.info(f"Retrieved {len(results)} package limits")
            return results
    except Exception as e:
        logger.error(f"Error fetching package limits: {str(e)}")
        raise


def get_list_heatmap_site_by_package_code(connection, package_code: str) -> List[Dict[str, Any]]:
    """
    Get list of heatmap sites by package code
    """
    try:
        with connection.cursor() as cursor:
            query = """
                    SELECT SITE_ID, DATE_MIN
                    FROM HEAT_MAP.HEATMAP_SITE
                    WHERE PACKAGE_CODE = %s
                      AND IS_DELETED = 0 \
                    """
            cursor.execute(query, (package_code,))
            results = cursor.fetchall()
            logger.info(f"Retrieved {len(results)} sites for package: {package_code}")
            return results
    except Exception as e:
        logger.error(f"Error fetching sites for package {package_code}: {str(e)}")
        raise


def update_date_min(connection, site_id: int, date_update: str):
    """
    Update the date_min for a site
    """
    try:
        with connection.cursor() as cursor:
            query = """
                    UPDATE HEAT_MAP.HEATMAP_SITE
                    SET date_min = %s
                    WHERE site_id = %s \
                    """
            cursor.execute(query, (date_update, site_id))
            logger.info(f"Updated date_min for site_id {site_id}")
    except Exception as e:
        logger.error(f"Error updating date_min for site {site_id}: {str(e)}")
        raise

if __name__ == "__main__":
    lambda_handler()
