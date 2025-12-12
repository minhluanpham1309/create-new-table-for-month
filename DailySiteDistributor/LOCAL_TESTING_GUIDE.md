# Hướng dẫn chạy Local

## 📋 Tổng quan

Hướng dẫn setup và test Lambda function ở local trước khi deploy lên AWS.

---

## 🔧 Yêu cầu

- Python 3.11+ (hoặc 3.9+)
- MySQL Server (local hoặc remote)
- pip (Python package manager)

---

## 🚀 Setup nhanh (5 phút)

### Bước 1: Install Python dependencies

```bash
# Create virtual environment (recommended)
python -m venv venv

# Activate virtual environment
# Windows:
venv\Scripts\activate
# Mac/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements_local.txt
```

### Bước 2: Setup MySQL Database

#### Option A: Sử dụng MySQL local

```bash
# Start MySQL service
# Windows:
net start MySQL80

# Mac (Homebrew):
brew services start mysql

# Linux:
sudo systemctl start mysql
```

#### Option B: Sử dụng Docker

```bash
# Run MySQL container
docker run --name mysql-test \
  -e MYSQL_ROOT_PASSWORD=root123 \
  -e MYSQL_DATABASE=heatmap_japan \
  -p 3306:3306 \
  -d mysql:8.0

# Wait for MySQL to start (khoảng 30 giây)
docker logs mysql-test
```

### Bước 3: Create test database và data

```bash
# Connect to MySQL
mysql -u root -p

# Run setup script
source setup_test_database.sql

# Hoặc
mysql -u root -p < setup_test_database.sql
```

**Generate nhiều test data:**

```sql
USE heatmap_japan;

-- Generate 2100 sites cho test 21 days
CALL generate_test_sites(2100);

-- Verify
SELECT COUNT(*) FROM sites WHERE status = 'active';
```

### Bước 4: Configure environment variables

```bash
# Copy .env.example thành .env
cp .env.example .env

# Edit .env file
nano .env  # hoặc dùng text editor
```

**Nội dung .env:**

```bash
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=root123
DB_NAME=heatmap_japan
```

### Bước 5: Chạy script

```bash
python local_sitelist_processor.py
```

---

## 📊 Expected Output

### Console Output

```
================================================================================
🚀 HeatmapJapan - Site List Processor (Local Version)
================================================================================

2024-12-12 10:00:00 - __main__ - INFO - Step 1: Connecting to database...
2024-12-12 10:00:00 - __main__ - INFO - Connecting to database: localhost:3306
2024-12-12 10:00:00 - __main__ - INFO - ✅ Database connection established successfully

2024-12-12 10:00:00 - __main__ - INFO - Step 2: Fetching all sites...
2024-12-12 10:00:00 - __main__ - INFO - Executing query to fetch sites...
2024-12-12 10:00:00 - __main__ - INFO - ✅ Retrieved 2100 sites from database

2024-12-12 10:00:00 - __main__ - INFO - Step 3: Splitting sites into 21-day schedule...
2024-12-12 10:00:00 - __main__ - INFO - 📊 Splitting 2100 sites into 21 days
2024-12-12 10:00:00 - __main__ - INFO -    Base sites per day: 100, Remainder: 0
2024-12-12 10:00:00 - __main__ - INFO -    Day  1: 100 sites (index    0 to   99)
2024-12-12 10:00:00 - __main__ - INFO -    Day  2: 100 sites (index  100 to  199)
...
2024-12-12 10:00:00 - __main__ - INFO -    Day 21: 100 sites (index 2000 to 2099)

================================================================================
📊 SCHEDULE SUMMARY
================================================================================
Total Sites: 2100
Days: 21

Day   Date         Day of Week  Sites Count 
--------------------------------------------------------------------------------
1     2024-12-12   Thursday     100         
2     2024-12-13   Friday       100         
3     2024-12-14   Saturday     100         
...
21    2025-01-01   Wednesday    100         
================================================================================

📁 Output files:
   - schedule_output.json (full schedule with all sites)
   - schedule_summary.json (summary only)

✅ Processing completed successfully!
```

### Output Files

#### schedule_summary.json (Nhỏ - chỉ summary)

```json
{
  "total_sites": 2100,
  "days": 21,
  "summary": {
    "day_1": {
      "date": "2024-12-12",
      "day_of_week": "Thursday",
      "sites_count": 100
    },
    "day_2": {
      "date": "2024-12-13",
      "day_of_week": "Friday",
      "sites_count": 100
    }
  }
}
```

#### schedule_output.json (Lớn - full data)

```json
{
  "message": "Sites successfully split into 21-day schedule",
  "total_sites": 2100,
  "days": 21,
  "schedule": {
    "day_1": {
      "date": "2024-12-12",
      "day_of_week": "Thursday",
      "sites_count": 100,
      "sites": [
        {
          "site_id": 1,
          "site_url": "https://example1.com",
          "site_name": "Example Site 1",
          "status": "active",
          "created_at": "2024-12-12 10:00:00"
        }
        // ... 99 more sites
      ]
    }
    // ... day_2 to day_21
  }
}
```

---

## 🧪 Testing với production database

### Connect to RDS

```bash
# .env
DB_HOST=heatmap-db.xxxxx.ap-southeast-1.rds.amazonaws.com
DB_PORT=3306
DB_USER=heatmap_user
DB_PASSWORD=production_password
DB_NAME=heatmap_japan_prod
```

**⚠️ Lưu ý**: 
- Cần whitelist IP của máy local trong RDS Security Group
- Hoặc dùng SSH tunnel qua EC2

### SSH Tunnel to RDS

```bash
# Trong terminal 1: Create tunnel
ssh -i your-key.pem -L 3307:rds-endpoint:3306 ec2-user@ec2-public-ip

# Trong terminal 2: Run script với port 3307
# .env
DB_HOST=localhost
DB_PORT=3307
DB_USER=heatmap_user
DB_PASSWORD=production_password
DB_NAME=heatmap_japan_prod
```

---

## 🔍 Debugging

### Enable verbose logging

Thêm vào đầu `local_sitelist_processor.py`:

```python
logging.basicConfig(
    level=logging.DEBUG,  # Change từ INFO sang DEBUG
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
```

### Test database connection only

```python
python -c "
import pymysql
from dotenv import load_dotenv
import os

load_dotenv()

try:
    conn = pymysql.connect(
        host=os.getenv('DB_HOST'),
        port=int(os.getenv('DB_PORT')),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME')
    )
    print('✅ Connection successful!')
    conn.close()
except Exception as e:
    print(f'❌ Connection failed: {e}')
"
```

### Common Issues

#### Error: "Access denied for user"

**Fix**: Check username/password trong .env

```bash
# Test connection
mysql -h localhost -u root -p
```

#### Error: "Can't connect to MySQL server"

**Fix**: 
1. Check MySQL đang chạy
2. Check port đúng (default 3306)
3. Check firewall

```bash
# Check MySQL status
# Windows:
sc query MySQL80

# Linux/Mac:
systemctl status mysql
```

#### Error: "Unknown database"

**Fix**: Create database

```sql
CREATE DATABASE heatmap_japan;
```

#### Error: "Module 'pymysql' not found"

**Fix**: Install dependencies

```bash
pip install -r requirements_local.txt
```

---

## 📝 Customize cho HeatmapJapan

### Điều chỉnh query theo schema thực tế

Edit `local_sitelist_processor.py`, function `get_all_sites()`:

```python
def get_all_sites(connection) -> List[Dict[str, Any]]:
    """Customize query theo schema HeatmapJapan"""
    with connection.cursor() as cursor:
        # Query theo schema thực tế
        query = """
            SELECT 
                s.site_id,
                s.site_key,
                s.domain,
                s.company_id,
                c.company_name,
                s.is_active,
                s.created_date
            FROM hm_sites s
            LEFT JOIN hm_companies c ON s.company_id = c.company_id
            WHERE s.is_active = 1
            AND s.deleted_at IS NULL
            ORDER BY s.site_id
        """
        cursor.execute(query)
        return cursor.fetchall()
```

### Thêm filters

```python
def get_all_sites(connection, company_id: int = None) -> List[Dict[str, Any]]:
    """Lấy sites với optional filter"""
    with connection.cursor() as cursor:
        query = """
            SELECT * FROM sites
            WHERE status = 'active'
        """
        
        params = []
        if company_id:
            query += " AND company_id = %s"
            params.append(company_id)
        
        query += " ORDER BY site_id"
        
        cursor.execute(query, params)
        return cursor.fetchall()
```

---

## 🔄 Workflow Integration

### Sử dụng output cho processing

```python
import json

# Load schedule từ file
with open('schedule_output.json', 'r') as f:
    schedule = json.load(f)

# Lấy sites cho ngày hôm nay
from datetime import datetime
today = datetime.now().strftime("%Y-%m-%d")

for day_key, day_data in schedule['schedule'].items():
    if day_data['date'] == today:
        sites = day_data['sites']
        print(f"Processing {len(sites)} sites for today")
        
        for site in sites:
            # Process site
            print(f"Processing: {site['site_url']}")
```

### Chạy daily với cron

```bash
# crontab -e
# Chạy mỗi ngày lúc 2:00 AM
0 2 * * * cd /path/to/project && /path/to/venv/bin/python local_sitelist_processor.py
```

---

## 🚀 Next Steps

Sau khi test thành công ở local:

1. ✅ Verify logic đúng
2. ✅ Customize query theo schema thực tế
3. ✅ Test với production data (qua SSH tunnel)
4. ✅ Deploy lên Lambda using Docker
5. ✅ Setup EventBridge cho scheduling

---

## 💡 Tips

### Performance testing

```python
import time

start = time.time()
# Run function
end = time.time()

print(f"Execution time: {end - start:.2f} seconds")
```

### Memory usage

```python
import sys

sites = get_all_sites(connection)
size_mb = sys.getsizeof(sites) / (1024 * 1024)
print(f"Memory usage: {size_mb:.2f} MB")
```

### Export to CSV

```python
import csv

def export_schedule_to_csv(schedule_data: Dict, filename: str = "schedule.csv"):
    """Export schedule summary to CSV"""
    with open(filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Day', 'Date', 'Day of Week', 'Sites Count'])
        
        for day_key, day_data in schedule_data['schedule'].items():
            day_num = day_key.replace('day_', '')
            writer.writerow([
                day_num,
                day_data['date'],
                day_data['day_of_week'],
                day_data['sites_count']
            ])
```

---

## 🎯 Comparison: Local vs Lambda

| Feature | Local | Lambda |
|---------|-------|--------|
| **Setup** | 5 phút | 30 phút |
| **Cost** | Free | ~$0.001/invocation |
| **Speed** | Fast | Fast (cold start ~2s) |
| **Debugging** | Easy | CloudWatch Logs |
| **Database** | Direct connection | VPC/Security Groups |
| **Scheduling** | Cron | EventBridge |
| **Best for** | Development, Testing | Production |

Anh test thử local xem có vấn đề gì không nhé!
