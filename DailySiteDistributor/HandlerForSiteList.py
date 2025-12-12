import json
import logging
import pymysql
import ssl
import urllib.request
import os
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

RDS_CA_BUNDLE_URL = 'https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem'

def download_rds_ca_bundle():
    """
    Download AWS RDS CA bundle
    Cache local để không phải download mỗi lần
    
    Returns:
        str: Path to CA bundle file
    """
    # Cache trong thư mục hiện tại
    ca_bundle_path = './rds-ca-bundle.pem'
    
    # Check if already downloaded
    if os.path.exists(ca_bundle_path):
        logger.info("✅ Using cached RDS CA bundle")
        return ca_bundle_path
    
    try:
        logger.info(f"📥 Downloading RDS CA bundle from AWS...")
        logger.info(f"   URL: {RDS_CA_BUNDLE_URL}")
        
        # Download CA bundle
        with urllib.request.urlopen(RDS_CA_BUNDLE_URL) as response:
            ca_data = response.read()
        
        # Write to file
        with open(ca_bundle_path, 'wb') as f:
            f.write(ca_data)
        
        logger.info("✅ RDS CA bundle downloaded and cached")
        logger.info(f"   Saved to: {ca_bundle_path}")
        
        return ca_bundle_path
        
    except Exception as e:
        logger.error(f"❌ Failed to download CA bundle: {str(e)}")
        logger.error("\n💡 Alternative: Download manually")
        logger.error(f"   curl -O {RDS_CA_BUNDLE_URL}")
        raise

def get_ssl_context():
    """
    Tạo SSL context với RDS CA bundle
    
    Returns:
        SSL context for pymysql
    """
    try:
        # Get SSL mode from environment
        ssl_mode = os.getenv('SSL_MODE', 'VERIFY_CA')
        
        # Download CA bundle
        ca_bundle_path = download_rds_ca_bundle()
        
        # Create SSL context
        ssl_context = ssl.create_default_context(cafile=ca_bundle_path)
        
        # Configure based on mode
        if ssl_mode == 'VERIFY_CA':
            # Verify CA certificate but not hostname (good cho RDS)
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_REQUIRED
            logger.info("🔒 SSL Mode: VERIFY_CA (verify certificate, skip hostname)")
            
        elif ssl_mode == 'VERIFY_IDENTITY':
            # Full verification
            ssl_context.check_hostname = True
            ssl_context.verify_mode = ssl.CERT_REQUIRED
            logger.info("🔒 SSL Mode: VERIFY_IDENTITY (full verification)")
            
        elif ssl_mode == 'SKIP_VERIFY':
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

def get_db_connection():
    """
    Kết nối RDS với SSL sử dụng AWS CA bundle
    KHÔNG CẦN JKS!
    
    Returns:
        pymysql.Connection: Database connection
    """
    try:
        logger.info("Connecting to database...")
        logger.info(f"Host: {os.getenv('DB_HOST')}")
        logger.info(f"Port: {os.getenv('DB_PORT', 3306)}")
        logger.info(f"Database: {os.getenv('DB_NAME')}")
        
        # Create SSL context with RDS CA
        ssl_context = get_ssl_context()
        
        # Database configuration
        db_config = {
            'host': os.getenv('DB_HOST'),
            'port': int(os.getenv('DB_PORT', 3306)),
            'user': os.getenv('DB_USER'),
            'password': os.getenv('DB_PASSWORD'),
            'database': os.getenv('DB_NAME'),
            'charset': 'utf8mb4',
            'cursorclass': pymysql.cursors.DictCursor,
            'connect_timeout': 10,
            'ssl': ssl_context
        }
        
        # Connect
        connection = pymysql.connect(**db_config)
        
        # Verify SSL connection
        with connection.cursor() as cursor:
            cursor.execute("SHOW STATUS LIKE 'Ssl_cipher'")
            result = cursor.fetchone()
            
            if result and result.get('Value'):
                logger.info(f"✅ Database connection established with SSL")
                logger.info(f"   SSL Cipher: {result['Value']}")
            else:
                logger.warning("⚠️  Connected but SSL cipher not detected")
        
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
    """
    Lấy toàn bộ sitelist từ database
    
    Args:
        connection: Database connection
        
    Returns:
        List[Dict]: List of sites với thông tin chi tiết
    """
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
        
        logger.info(f"   Day {day:2d}: {len(sublists[day]):3d} sites (index {start_idx:4d} to {end_idx-1:4d})")
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

def save_schedule_to_file(schedule_data: Dict[str, Any], filename: str = "schedule_output.json"):
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(schedule_data, f, indent=2, default=str, ensure_ascii=False)
        
        logger.info(f"✅ Schedule saved to {filename}")
    except Exception as e:
        logger.error(f"❌ Error saving schedule to file: {str(e)}")

def print_summary(schedule_data: Dict[str, Any]):
    print("\n" + "=" * 80)
    print("📊 SCHEDULE SUMMARY")
    print("=" * 80)
    print(f"Total Sites: {schedule_data['total_sites']}")
    print(f"Days: {schedule_data['days']}")
    print()
    print(f"{'Day':<5} {'Date':<12} {'Day of Week':<12} {'Sites Count':<12}")
    print("-" * 80)
    
    for day in range(1, 22):
        day_key = f"day_{day}"
        day_info = schedule_data['schedule'][day_key]
        print(f"{day:<5} {day_info['date']:<12} {day_info['day_of_week']:<12} {day_info['sites_count']:<12}")
    
    print("=" * 80)
    print()

def main():
    print("\n" + "=" * 80)
    print("🚀 HeatmapJapan - Site List Processor (Local Version)")
    print("=" * 80)
    print()
    
    connection = None
    
    try:
        # Step 1: Connect to database
        logger.info("Step 1: Connecting to database...")
        connection = get_db_connection()
        
        # Step 2: Get all sites
        logger.info("\nStep 2: Fetching all sites...")
        sites = get_all_sites(connection)
        
        if not sites:
            logger.warning("⚠️  No active sites found")
            return
        
        # Step 3: Split into 21 sublists
        logger.info("\nStep 3: Splitting sites into 21-day schedule...")
        sublists = split_sites_into_21_days(sites)
        
        # Step 4: Generate schedule
        logger.info("\nStep 4: Generating schedule with dates...")
        schedule = generate_schedule(sublists)
        
        # Step 5: Prepare response data
        schedule_data = {
            'message': 'Sites successfully split into 21-day schedule',
            'total_sites': len(sites),
            'days': 21,
            'schedule': schedule,
            'summary': {
                day: {
                    'date': info['date'],
                    'day_of_week': info['day_of_week'],
                    'sites_count': info['sites_count']
                }
                for day, info in schedule.items()
            }
        }
        
        # Step 6: Print summary
        print_summary(schedule_data)
        
        # Step 7: Save to file
        logger.info("Step 5: Saving schedule to file...")
        save_schedule_to_file(schedule_data, "schedule_output.json")
        
        # Step 8: Save summary only (smaller file)
        summary_data = {
            'total_sites': schedule_data['total_sites'],
            'days': schedule_data['days'],
            'summary': schedule_data['summary']
        }
        save_schedule_to_file(summary_data, "schedule_summary.json")
        
        logger.info("\n✅ Processing completed successfully!")
        print("\n📁 Output files:")
        print("   - schedule_output.json (full schedule with all sites)")
        print("   - schedule_summary.json (summary only)")
        
    except Exception as e:
        logger.error(f"\n❌ Error in main execution: {str(e)}", exc_info=True)
        return 1
        
    finally:
        # Close database connection
        if connection:
            connection.close()
            logger.info("\n🔒 Database connection closed")
    
    return 0

if __name__ == "__main__":
    exit(main())
