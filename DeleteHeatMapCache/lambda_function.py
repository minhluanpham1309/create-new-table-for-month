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

jst = pytz.timezone("Asia/Tokyo")

def lambda_handler(event=None, context=None):
    cnx = None
    cursor = None
    region = get_region()
    start_time = datetime.now(jst)

    try:
        logger.info("Lambda function started: truncate table")

        secret = run_step("get_secret", get_secret, region)

        cnx = run_step("get_db_connection", get_db_connection, secret)
        cursor = cnx.cursor()

        run_step("truncate_table", truncate_table, cnx)

        if cnx:
            cnx.commit()

        end_time = datetime.now(jst)
        execution_time = (end_time - start_time).total_seconds()

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "message": "Truncated table successfully: HEATMAP_CACHE",
                    "execute_time": execution_time,
                }
            ),
        }

    except Exception as e:
        if cnx:
            try:
                cnx.rollback()
                logger.info("DB rollback executed")
            except Exception:
                logger.exception("DB rollback failed")
        raise

    finally:
        if cursor:
            cursor.close()
        if cnx:
            cnx.close()


def truncate_table(connection):

    sql="""TRUNCATE TABLE HEAT_MAP.HEATMAP_CACHE"""

    with connection.cursor() as cursor:
        logger.info(f"Executing: {sql}")
        cursor.execute(sql)


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
        ssl_context.verify_mode = ssl.CERT_REQUIRED
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
    secret_name = os.environ.get("RDS_SECRET_NAME", "rds/heatmap-db-secret")

    config = boto3.session.Config(
        connect_timeout=5,
        read_timeout=10,
        retries={"max_attempts": 3},
    )

    logger.info("Creating boto3 client for Secrets Manager...")
    client = boto3.client("secretsmanager", region_name=region, config=config)

    logger.info("Fetching secret value from Secrets Manager...")
    try:
        response = client.get_secret_value(SecretId=secret_name)
        return json.loads(response["SecretString"])
    except Exception:
        logger.error(f"Failed to fetch secret {secret_name}", exc_info=True)
        raise


def get_region() -> str:
    return os.environ.get("AWS_REGION", "ap-northeast-1")


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