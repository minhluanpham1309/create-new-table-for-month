import json
import logging
import pymysql
import ssl
import urllib.request
import os
import boto3
import certifi
from datetime import datetime, timedelta
from typing import List, Dict, Any
from dotenv import load_dotenv

# Load environment variables từ .env file
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

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

        sublists = run_step("split_sites_into_21_days", split_sites_into_21_days, sites)
        
        schedule = run_step("generate_schedule", generate_schedule, sublists)

        run_step("insert_schedule_to_db", insert_schedule_to_db, cnx, schedule)
        
    except Exception as e:
        if cnx:
            cnx.rollback()
        logger.error(f"❌ Error in lambda_handler: {str(e)}", exc_info=True)
    else:
        if cnx:
            cnx.commit()
    finally:
        if cursor:
            cursor.close()
        if cnx:
            cnx.close()



def get_ssl_context():
    try:
        # Get SSL mode from environment
        ssl_mode = os.getenv('SSL_MODE', 'VERIFY_CA')
        
        # Download CA bundle
        ca_bundle_path = certifi.where()
        
        # Create SSL context
        ssl_context = ssl.create_default_context(cafile=ca_bundle_path)
        
        # Configure based on mode
        if ssl_mode == 'SKIP_VERIFY':
            # Skip verification (not recommended)
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            logger.info("⚠️  SSL Mode: SKIP_VERIFY (no verification)")
            
        else:
            # Default to VERIFY_CA
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_REQUIRED
            logger.info("🔒 SSL Mode: VERIFY_CA (default)")
        
        logger.info("✅ SSL context created")
        return ssl_context
        
    except Exception as e:
        logger.error(f"❌ Failed to create SSL context: {str(e)}")
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
            'database': secret.get('dbname', os.getenv('DB_NAME')),
            'charset': 'utf8mb4',
            'connect_timeout': 10,
            'cursorclass': pymysql.cursors.DictCursor,
            'ssl': ssl_context
        }
        
        # Connect
        logger.info("🔌 Connecting to database...")
        connection = pymysql.connect(**db_config)
        logger.info("✅ Database connection established")      
        return connection
        
    except pymysql.err.OperationalError as e:
        error_code = e.args[0] if e.args else None
        
        if error_code == 2003:
            logger.error("❌ Cannot connect to database server")
            logger.error("\n💡 Troubleshooting:")
            logger.error("   1. Check DB_HOST is correct RDS endpoint")
            logger.error("   2. Check Security Group allows your IP")
            logger.error("   3. Check RDS is publicly accessible (if connecting from outside VPC)")
        elif error_code == 1045:
            logger.error("❌ Access denied - check username/password")
        else:
            logger.error(f"❌ Database connection error: {str(e)}")
        
        raise
        
    except Exception as e:
        logger.error(f"❌ Failed to connect to database: {str(e)}")
        logger.error("\n💡 Troubleshooting:")
        logger.error("   1. Verify credentials in .env file")
        logger.error("   2. Check network connectivity to RDS")
        logger.error("   3. Verify SSL_MODE setting")

def get_all_sites(connection) -> List[Dict[str, Any]]:
    try:
        with connection.cursor() as cursor:
            query = """
                SELECT 
                    site_id
                FROM HEAT_MAP.HEATMAP_SITE
                WHERE status = 1 AND is_deleted = 0
            """
            
            logger.info("Executing query to fetch sites...")
            cursor.execute(query)
            sites = cursor.fetchall()
            
            logger.info(f"✅ Retrieved {len(sites)} sites from database")
            return sites
            
    except Exception as e:
        logger.error(f"❌ Error fetching sites: {str(e)}")
        raise

def split_sites_into_21_days(sites: List[Dict[str, Any]]) -> Dict[int, List[Dict[str, Any]]]:
    if not sites:
        logger.warning("⚠️  No sites to split")
        return {}
    
    total_sites = len(sites)
    sites_per_day = total_sites // 21
    remainder = total_sites % 21
    
    logger.info(f"📊 Splitting {total_sites} sites into 21 days")
    logger.info(f"   Base sites per day: {sites_per_day}, Remainder: {remainder}")
    
    sublists = {}
    start_idx = 0
    
    for day in range(1, 22):
        end_idx = start_idx + sites_per_day + (1 if day <= remainder else 0)
        sublists[day] = sites[start_idx:end_idx]
        start_idx = end_idx
    
    return sublists

def generate_schedule(sublists: Dict[int, List[Dict[str, Any]]]) -> Dict[str, Any]:
    today = datetime.now()
    schedule = {}
    
    logger.info("📅 Generating schedule...")
    
    for day in range(1, 22):
        target_date = today + timedelta(days=day-1)
        
        schedule[f"day_{day}"] = {
            "date": target_date.strftime("%Y-%m-%d"),
            "day_of_week": target_date.strftime("%A"),
            "sites_count": len(sublists.get(day, [])),
            "sites": sublists.get(day, [])
        }
    
    return schedule

def insert_schedule_to_db(connection, schedule: Dict[str, Any]):
    try:
        with connection.cursor() as cursor:
            # Prepare insert query
            insert_query = """
                INSERT INTO HEAT_MAP.MONTHLY_ADDING_SITE_TABLES 
                (APPLY_ON, LIST_SITES, IS_ADDED)
                VALUES (%s, %s, %s)
            """
            
            inserted_count = 0
            
            for day_key, day_data in schedule.items():
                apply_on = day_data['date']
                
                site_ids = [site['site_id'] for site in day_data['sites']]
                list_sites_json = json.dumps(site_ids, ensure_ascii=False)
                
                is_added = 0
                
                
                cursor.execute(insert_query, (apply_on, list_sites_json, is_added))
                inserted_count += 1
            
            logger.info(f"✅ Successfully inserted {inserted_count} records into MONTHLY_ADDING_SITE_TABLES")
            
    except Exception as e:
        logger.error(f"❌ Error inserting schedule to database: {str(e)}")
        raise

def get_secret(region):
    secret_name = os.environ.get('RDS_SECRET_NAME', 'rds/db-test-private')
    if not secret_name:
        raise ValueError("Missing environment variable: RDS_SECRET_NAME")

    logger.info("Creating boto3 client for Secrets Manager...")
    client = boto3.client('secretsmanager', region_name=region)

    logger.info("Fetching secret value from Secrets Manager...")
    response = client.get_secret_value(SecretId=secret_name)

    return json.loads(response['SecretString'])

def get_region() -> str:
    region_name = os.environ.get('AWS_REGION', 'ap-northeast-1')
    if not region_name:
        raise ValueError("Missing environment variable: AWS_REGION")
    return region_name

def run_step(step_name: str, func, *args, **kwargs):
    try:
        logger.info("")
        logger.info(f"====== ⏳ START STEP: {step_name} ======")
        result = func(*args, **kwargs)
        logger.info(f"====== ✅ DONE STEP: {step_name} ======")
        logger.info("")
        return result
    except Exception as e:
        logger.error(f"====== ❌ ERROR STEP: {step_name} ======")
        logger.error(f"Exception: {str(e)}")
        logger.error("")
        raise

if __name__ == "__main__":
    lambda_handler()
