"""
Local version của Lambda function - để test trước khi deploy

Cách chạy:
    python local_sitelist_processor.py

Yêu cầu:
    - MySQL đang chạy
    - Database credentials trong .env file hoặc environment variables
"""

import json
import logging
import pymysql
from datetime import datetime, timedelta
from typing import List, Dict, Any
import os
from dotenv import load_dotenv

# Load environment variables từ .env file
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Database configuration
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'port': int(os.getenv('DB_PORT', 3306)),
    'user': os.getenv('DB_USER', 'root'),
    'password': os.getenv('DB_PASSWORD', ''),
    'database': os.getenv('DB_NAME', 'heatmap_japan'),
    'charset': 'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor,
    'connect_timeout': 5
}

def get_db_connection():
    """
    Tạo kết nối đến MySQL database
    
    Returns:
        pymysql.Connection: Database connection object
    """
    try:
        logger.info(f"Connecting to database: {DB_CONFIG['host']}:{DB_CONFIG['port']}")
        connection = pymysql.connect(**DB_CONFIG)
        logger.info("✅ Database connection established successfully")
        return connection
    except Exception as e:
        logger.error(f"❌ Failed to connect to database: {str(e)}")
        raise

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
            # Query lấy toàn bộ sites - điều chỉnh theo schema của anh
            query = """
                SELECT 
                    site_id,
                    site_url,
                    site_name,
                    status,
                    created_at,
                    updated_at
                FROM sites
                WHERE status = 'active'
                ORDER BY site_id
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
    """
    Chia sitelist thành 21 sublists cho 21 ngày
    
    Args:
        sites: List of all sites
        
    Returns:
        Dict: Dictionary với key là day (1-21) và value là sublist of sites
    """
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
        # Phân bổ đều sites, các ngày đầu sẽ có thêm 1 site nếu có remainder
        end_idx = start_idx + sites_per_day + (1 if day <= remainder else 0)
        sublists[day] = sites[start_idx:end_idx]
        
        logger.info(f"   Day {day:2d}: {len(sublists[day]):3d} sites (index {start_idx:4d} to {end_idx-1:4d})")
        start_idx = end_idx
    
    return sublists

def generate_schedule(sublists: Dict[int, List[Dict[str, Any]]]) -> Dict[str, Any]:
    """
    Tạo schedule chi tiết cho 21 ngày
    
    Args:
        sublists: Dictionary of sublists by day
        
    Returns:
        Dict: Complete schedule with dates and sites
    """
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
    """
    Lưu schedule ra file JSON
    
    Args:
        schedule_data: Schedule data to save
        filename: Output filename
    """
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(schedule_data, f, indent=2, default=str, ensure_ascii=False)
        
        logger.info(f"✅ Schedule saved to {filename}")
    except Exception as e:
        logger.error(f"❌ Error saving schedule to file: {str(e)}")

def print_summary(schedule_data: Dict[str, Any]):
    """
    In ra summary của schedule
    
    Args:
        schedule_data: Schedule data
    """
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
    """
    Main execution function
    """
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
