import json
import logging
import pymysql
import ssl
import os
import boto3
from datetime import datetime, timedelta
from typing import List, Dict, Any
import pytz
import numpy as np
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


def lambda_handler(event=None, context=None):
    cnx = None
    cursor = None
    region = get_region()

    try:
        logger.info("Lambda function started")

        secret = run_step("get_secret", get_secret, region)

        cnx = run_step("get_db_connection", get_db_connection, secret)
        cursor = cnx.cursor()

        sites = run_step("get_all_sites", get_all_sites, cnx)

        sublists = run_step("split_into_chunk", split_into_chunk, sites)

        schedule = run_step("generate_schedule", generate_schedule, sublists)

        run_step("insert_schedule_to_db", insert_schedule_to_db, cnx, schedule)

        # Prepare success response
        if cnx:
            cnx.commit()

        logger.info(f"Lambda completed successfully - total : {len(sites)} sites")

    except Exception as e:
        if cnx:
            cnx.rollback()
        logger.error(f"Error in lambda_handler: {str(e)}", exc_info=True)
        logger.error(f"Event: {json.dumps(event)}")
        raise

    finally:
        if cursor:
            cursor.close()
        if cnx:
            cnx.close()

def get_ssl_context(region: str = 'ap-northeast-1'):
    """Create SSL context with TLS 1.2+ (download CA bundle from AWS)"""
    try:
        ca_file_path = os.path.join(os.path.dirname(__file__), 'certs', f'{region}-bundle.pem')

        # Fallback to global bundle if region-specific not found
        if not os.path.exists(ca_file_path):
            ca_file_path = os.path.join(os.path.dirname(__file__), 'certs', 'global-bundle.pem')

        if not os.path.exists(ca_file_path):
            raise FileNotFoundError(f"CA bundle not found at {ca_file_path}")

        logger.info(f"📥 Loading CA bundle from: {ca_file_path}")

        # Create SSL context with TLS 1.2+
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ssl_context.load_verify_locations(cafile=ca_file_path)

        # Configure verification
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_REQUIRED
        logger.info("🔒 SSL: VERIFY_CA")

        # Set minimum TLS 1.2
        ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2

        return ssl_context

    except Exception as e:
        logger.error(f"Failed to create SSL context: {str(e)}")
        raise

def get_db_connection(secret):
    try:
        # Create SSL context with RDS CA
        ssl_context = get_ssl_context()

        # Database configuration
        db_config = {
            'host': secret.get('host', os.getenv('DB_HOST')),
            'port': int(secret.get('port', os.getenv('DB_PORT', 3306))),
            'user': secret.get('username', os.getenv('DB_USER')),
            'password': secret.get('password', os.getenv('DB_PASSWORD')),
            'database': secret.get('dbname', os.getenv('DB_NAME', "HEAT_MAP")),
            'charset': 'utf8mb4',
            'connect_timeout': 10,
            'cursorclass': pymysql.cursors.DictCursor,
            'ssl': ssl_context
        }

        # Connect
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


def get_all_sites(connection) -> List[Dict[str, Any]]:
    try:
        with connection.cursor() as cursor:
            query = """
                    SELECT site_id
                    FROM HEAT_MAP.HEATMAP_SITE
                    """

            logger.info("Executing query to fetch sites...")
            cursor.execute(query)
            sites = cursor.fetchall()

            logger.info(f"✅ Retrieved {len(sites)} sites from database")
            return sites

    except Exception as e:
        logger.error(f"Error fetching sites: {str(e)}")
        raise

def split_into_chunk(sites: List[Dict[str, Any]]) -> Dict[int, List[Dict[str, Any]]]:
    if not sites:
        logger.error("No sites to split...")
        return {day: [] for day in range(1, SITE_CHUNK_DAYS + 1)}

    n = len(sites)
    base = n // SITE_CHUNK_DAYS
    extra = n % SITE_CHUNK_DAYS

    # Create sizes array
    sizes = np.full(SITE_CHUNK_DAYS, base)
    sizes[:extra] += 1

    # Split
    indices = np.cumsum(sizes)[:-1]
    chunks = np.split(sites, indices)

    # Convert to dict
    return {day: chunk.tolist() for day, chunk in enumerate(chunks, 1)}

def generate_schedule(sublists: Dict[int, List[Dict[str, Any]]]) -> Dict[str, Any]:

    # Start_date is 01 st every month
    jst = pytz.timezone('Asia/Tokyo')
    today = datetime.now(jst)
    start_date = datetime(today.year, today.month, 1, tzinfo=jst)
    logger.info("Generating schedule...")

    return {
        f"day_{day}": {
            "date": (date := start_date + timedelta(days=day - 1)).strftime("%Y-%m-%d"),
            "day_of_week": date.strftime("%A"),
            "sites_count": len(sites := sublists.get(day, [])),
            "sites": sites
        }
        for day in sublists.keys()
    }

def insert_schedule_to_db(connection, schedule: Dict[str, Any]):
    try:
        with connection.cursor() as cursor:
            # Prepare insert query
            insert_query = """
                           INSERT INTO HEAT_MAP.MONTHLY_ADDING_SITE_TABLES
                               (APPLY_ON, LIST_SITES)
                           VALUES (%s, %s) 
                           ON DUPLICATE KEY UPDATE
                                LIST_SITES = VALUES(LIST_SITES)
                           """

            inserted_count = 0

            for day_key, day_data in schedule.items():
                apply_on = day_data['date']

                site_ids = [site['site_id'] for site in day_data['sites']]
                list_sites_json = json.dumps(site_ids, ensure_ascii=False)

                cursor.execute(insert_query, (apply_on, list_sites_json))
                inserted_count += 1

            logger.info(f"Successfully inserted {inserted_count} records into MONTHLY_ADDING_SITE_TABLES")

    except Exception as e:
        logger.error(f"Error inserting schedule to database: {str(e)}")
        raise


def get_secret(region):
    secret_name = os.environ.get('RDS_SECRET_NAME', 'rds/db-test-private')

    # Create client with timeout config
    config = boto3.session.Config(
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

if __name__ == "__main__":
    lambda_handler()