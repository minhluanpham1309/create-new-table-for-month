# Monthly Site Scheduler Lambda Function

Lambda function that automatically distributes and schedules sites into tables over a 21-day cycle for the HeatmapJapan system.

## 📋 Purpose

This function performs the following tasks:
1. Fetches all active sites from the database
2. Splits sites into 21 equal groups
3. Creates a schedule for the next 21 days
4. Saves the schedule to the `MONTHLY_ADDING_SITE_TABLES` table

## 🏗️ Architecture
```
┌─────────────┐      ┌──────────────┐      ┌─────────────┐
│   GitHub    │─────▶│   Lambda     │─────▶│  RDS MySQL  │
│   Actions   │      │   Function   │      │  Database   │
└─────────────┘      └──────────────┘      └─────────────┘
                            │
                            ▼
                     ┌──────────────┐
                     │   Secrets    │
                     │   Manager    │
                     └──────────────┘
```

## 🗄️ Database Schema

### Table: MONTHLY_ADDING_SITE_TABLES
```sql
CREATE TABLE HEAT_MAP.MONTHLY_ADDING_SITE_TABLES (
    ID INT AUTO_INCREMENT PRIMARY KEY,
    APPLY_ON DATE NOT NULL,
    LIST_SITES TEXT NOT NULL,
    IS_ADDED BIT DEFAULT b'0' NOT NULL,
    LOG VARCHAR(100) NULL,
    CREATED DATETIME DEFAULT CURRENT_TIMESTAMP NULL,
    UPDATED DATETIME DEFAULT CURRENT_TIMESTAMP NULL ON UPDATE CURRENT_TIMESTAMP
);
```

**Columns:**
- `ID`: Primary key, auto increment
- `APPLY_ON`: Date when the schedule should be applied
- `LIST_SITES`: JSON array containing list of site_id
- `IS_ADDED`: Flag indicating if processed (0 = not processed, 1 = processed)
- `LOG`: Notes about the schedule
- `CREATED`: Record creation timestamp
- `UPDATED`: Last update timestamp

## 📁 Project Structure
```
monthly-site-scheduler/
├── .github/
│   └── workflows/
│       └── deploy-lambda.yml      # GitHub Actions workflow
├── lambda_function.py              # Main Lambda function
├── requirements.txt                # Python dependencies
├── .gitignore                      # Git ignore file
├── .env.example                    # Environment variables template
└── README.md                       # This file
```

## 🚀 Deployment

### Prerequisites

1. **AWS Account** with permissions:
   - Lambda: UpdateFunctionCode, UpdateFunctionConfiguration
   - Secrets Manager: GetSecretValue
   - RDS: Connect to database

2. **GitHub Repository** with secrets:
   - `AWS_ACCESS_KEY_ID`
   - `AWS_SECRET_ACCESS_KEY`
   - `RDS_SECRET_NAME`

### Setup GitHub Secrets

1. Navigate to: `GitHub Repo → Settings → Secrets and variables → Actions`
2. Add the following secrets:
```
AWS_ACCESS_KEY_ID=<your-access-key>
AWS_SECRET_ACCESS_KEY=<your-secret-key>
RDS_SECRET_NAME=rds/db-test-private
```

### Automatic Deployment

Function automatically deploys when pushing code to branches:
- `main` → Production
- `develop` → Development
```bash
# Push to trigger deployment
git add .
git commit -m "Update lambda function"
git push origin main
```

### Manual Deployment

Trigger manual deployment:
1. Go to `Actions` tab in GitHub
2. Select workflow "Deploy Lambda Function"
3. Click "Run workflow"

## 🔧 Local Development

### Setup Local Environment
```bash
# Clone repository
git clone 
cd monthly-site-scheduler

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Configure Environment Variables

Create `.env` file:
```env
# Database Configuration
DB_HOST=your-rds-endpoint.rds.amazonaws.com
DB_PORT=3306
DB_USER=admin
DB_PASSWORD=your-password
DB_NAME=HEAT_MAP

# AWS Configuration
AWS_REGION=ap-northeast-1
RDS_SECRET_NAME=rds/db-test-private

# SSL Configuration
SSL_MODE=VERIFY_CA  # Options: VERIFY_CA, SKIP_VERIFY
```

### Run Locally
```bash
# Test function
python lambda_function.py
```

## 📦 Dependencies
```txt
pymysql>=1.1.0          # MySQL connector
python-dotenv>=1.0.0    # Environment variables
boto3>=1.34.0           # AWS SDK
```

## 🔒 Security

### SSL/TLS Configuration

Function uses SSL/TLS to connect to RDS:
- Downloads RDS CA Bundle from AWS
- Verifies certificate authority
- Supports 2 modes:
  - `VERIFY_CA`: Verify CA certificate (recommended)
  - `SKIP_VERIFY`: Skip verification (not recommended)

### Secrets Management

Credentials are stored in AWS Secrets Manager:
```json
{
  "host": "your-rds-endpoint.rds.amazonaws.com",
  "port": 3306,
  "username": "admin",
  "password": "your-password",
  "dbname": "HEAT_MAP"
}
```

## 📊 Workflow Logic

### 1. Fetch Sites
```sql
SELECT site_id 
FROM HEAT_MAP.HEATMAP_SITE 
WHERE status = 1 AND is_deleted = 0
```

### 2. Split into 21 Days

Distribution algorithm:
- Total sites: N
- Sites per day: N ÷ 21
- Remainder: N % 21
```python
Day 1-remainder: (N ÷ 21) + 1 sites
Day (remainder+1)-21: N ÷ 21 sites
```

### 3. Generate Schedule

Creates schedule for the next 21 days starting from today:
```json
{
  "day_1": {
    "date": "2024-12-17",
    "sites_count": 150,
    "sites": [{"site_id": 1}, {"site_id": 2}, ...]
  },
  ...
}
```

### 4. Insert to Database

Insert into `MONTHLY_ADDING_SITE_TABLES`:
```sql
INSERT INTO HEAT_MAP.MONTHLY_ADDING_SITE_TABLES 
(APPLY_ON, LIST_SITES, IS_ADDED)
VALUES 
('2024-12-17', '[1,2,3,...]', 0)
```

## 📝 Logging

Function uses Python logging module with format:
```
2024-12-17 10:30:45 - __main__ - INFO - Lambda function started
2024-12-17 10:30:46 - __main__ - INFO - ====== ⏳ START STEP: get_secret ======
2024-12-17 10:30:47 - __main__ - INFO - ====== ✅ DONE STEP: get_secret ======
```

### Log Levels
- `INFO`: Normal operation logs
- `WARNING`: Warnings (e.g., empty sites list)
- `ERROR`: Errors during processing

## 🧪 Testing

### Manual Testing
```bash
# Test database connection
python -c "from lambda_function import get_db_connection, get_secret; 
           cnx = get_db_connection(get_secret('ap-northeast-1')); 
           print('✅ Connection successful')"

# Test site retrieval
python lambda_function.py
```

## 🔄 CI/CD Pipeline

### GitHub Actions Workflow
```yaml
Trigger: Push to main/develop
↓
Install Dependencies
↓
Create ZIP Package
↓
Deploy to Lambda
↓
Update Configuration
↓
Success ✅
```

### Deployment Steps

1. ✅ Checkout code from repository
2. ✅ Setup Python 3.11
3. ✅ Install dependencies to `./build`
4. ✅ Copy lambda_function.py
5. ✅ Create deployment ZIP
6. ✅ Configure AWS credentials
7. ✅ Update Lambda function code
8. ✅ Wait for update completion
9. ✅ Update environment variables

