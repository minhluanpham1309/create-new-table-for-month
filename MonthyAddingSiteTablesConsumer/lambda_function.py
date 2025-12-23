import json
import logging
import pymysql
import ssl
import os
import boto3
from datetime import datetime
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

DATABASE_TEMPLATE_NAME = 'monthly_heatmap_table_template'

jst = pytz.timezone('Asia/Tokyo')

class ResultCreatedTable:

    def __init__(self):
        self.total_sites_success = 0
        self.total_sites_failed = 0
        self.failed_items = []

    def to_dict(self):
        return {
            'total_sites_success': self.total_sites_success,
            'total_sites_failed': self.total_sites_failed,
            'failed_items': self.failed_items
        }

class SearchDate:
    def __init__(self, date: datetime):
        self.date = date

    @classmethod
    def now(cls):
        return cls(datetime.now(jst))

    def original_format(self) -> str:
        return self.date.strftime('%Y-%m-%d')

    def year_month_format(self) -> str:
        return self.date.strftime('%Y%m')

    def plus_months(self, months: int):
        new_month = self.date.month + months
        new_year = self.date.year

        while new_month > 12:
            new_month -= 12
            new_year += 1

        try:
            new_date = self.date.replace(year=new_year, month=new_month)
        except ValueError:
            import calendar
            last_day = calendar.monthrange(new_year, new_month)[1]
            new_date = self.date.replace(year=new_year, month=new_month, day=last_day)

        return SearchDate(new_date)

def lambda_handler(event=None, context=None):
    cnx = None
    cursor = None
    region = get_region()
    start_time = datetime.now(jst)
    try:
        logger.info("Lambda function started")

        secret = run_step("get_secret", get_secret, region)

        cnx = run_step("get_db_connection", get_db_connection, secret)
        cursor = cnx.cursor()

        all_sites = run_step("get_all_sites", get_all_sites, cnx)

        current_date = SearchDate.now()
        current_date_str = current_date.original_format()

        apply_sites = run_step("find_by_apply_on", find_by_apply_on, cnx, current_date_str)

        # Handle None case
        if not apply_sites:
            logger.warning(f"No record found for {current_date_str}")

            # Create empty result
            empty_result = ResultCreatedTable()

            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': 'No record to process',
                    'result': empty_result.to_dict(),
                    'execute_time': 0
                })
            }

        row_id = apply_sites['ID']

        sub_sites = json.loads(apply_sites['LIST_SITES'])

        next_month = current_date.plus_months(1)

        result = run_step("create_tables_for_sites", create_tables_for_sites, cnx, sub_sites, all_sites, next_month)

        run_step("update_log", update_log, cnx, result, row_id)

        # Prepare success response
        if cnx:
            cnx.commit()

        end_time = datetime.now(jst)
        execution_time = (end_time - start_time).total_seconds()

        logger.info(f"Completed: {result.total_sites_success} sites success, {result.total_sites_failed} sites failed")

        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Monthly tables created successfully',
                'result': result.to_dict(),
                'execute_time': execution_time
            })
        }

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


def get_all_sites(connection):
    try:
        with connection.cursor() as cursor:
            query = """
                    SELECT site_id
                    FROM HEAT_MAP.HEATMAP_SITE
                    """

            logger.info("Executing query to fetch sites...")
            cursor.execute(query)
            rows = cursor.fetchall()

            return [int(row['site_id']) for row in rows]

    except Exception as e:
        logger.error(f"Error fetching sites: {str(e)}")
        raise


def find_by_apply_on(connection, apply_on_date: str):
    try:
        with connection.cursor() as cursor:
            query = """
                    SELECT ID, LIST_SITES
                    FROM HEAT_MAP.MONTHLY_ADDING_SITE_TABLES
                    WHERE APPLY_ON = %s LIMIT 1
                    """
            cursor.execute(query, (apply_on_date,))
            row = cursor.fetchone()

            if row:
                logger.info(f"Found record ID={row['ID']} for APPLY_ON = {apply_on_date}")
                return row
            else:
                logger.warning(f"No record found for APPLY_ON = {apply_on_date}")
                return None

    except Exception as e:
        logger.error(f"Error in find_by_apply_on: {str(e)}")
        raise


def create_monthly_table(cnx, database_name: str, table_suffix: str, target_date: SearchDate):
    month_prefix = target_date.year_month_format()

    create_table_sql = (
        f"CREATE TABLE IF NOT EXISTS `{database_name}`.`{month_prefix}_{table_suffix}` "
        f"LIKE `{DATABASE_TEMPLATE_NAME}`.`template_{table_suffix}`;"
    )

    with cnx.cursor() as cursor:
        cursor.execute(create_table_sql)


def create_tables_for_sites(cnx, site_list: list, list_hm_site: list, next_month: SearchDate) -> ResultCreatedTable:

    result = ResultCreatedTable()
    table_suffixes = ['referrer', 'click', 'read', 'scroll']

    # Convert to set cho O(1) lookup
    hm_site_set = set(list_hm_site)

    total_sites = len(site_list)
    logger.info(f"Processing {total_sites} sites")

    for idx, site_id in enumerate(site_list, 1):
        try:
            if site_id not in hm_site_set:
                result.total_sites_success += 1
                continue

            for table_suffix in table_suffixes:
                create_monthly_table(cnx, site_id, table_suffix, next_month)

            cnx.commit()
            result.total_sites_success += 1

        except Exception as e:
            result.total_sites_failed += 1
            result.failed_items.append(site_id)
            logger.error(f"Error {site_id}: {str(e)}")

    return result

def update_log(cnx, result: ResultCreatedTable, row_id: int):
    try:
        has_error = result.total_sites_failed > 0

        if has_error:
            log_message = "Errors: " + json.dumps(result.failed_items, ensure_ascii=False)
        else:
            log_message = "Success all"

        with cnx.cursor() as cursor:
            query = """
                    UPDATE HEAT_MAP.MONTHLY_ADDING_SITE_TABLES
                    SET LOG      = %s,
                        IS_ADDED = 1
                    WHERE ID = %s 
                    """
            cursor.execute(query, (log_message, row_id))
            logger.info(f"Updated LOG for record ID {row_id}")

    except Exception as e:
        logger.error(f"Error updating log for record {row_id}: {str(e)}")
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