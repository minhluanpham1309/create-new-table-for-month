module "heatmap_japan_dev" {
  source = "../../"

  # Basic configuration
  aws_region   = "ap-northeast-1"
  environment  = "dev"
  project_name = "heatmap-japan"

  # Lambda functions configuration (if needed)
  monthly_adding_site_tables_producers = {
    # Lambda function configuration
    lambda_function_name = "MonthlyAddingSiteTablesProducer"
    lambda_handler       = "lambda_function.lambda_handler"
    lambda_runtime       = "python3.11"

    lambda_timeout     = 900
    lambda_memory_size = 256

    lambda_environment_variables = {
      SITE_CHUNK_DAYS = 21
      RDS_SECRET_NAME = "rds/db-test-private"
    }

    # Replace these ARNs with your IAM roles
    lambda_role_arn    = "arn:aws:iam::683918607581:role/excute-lambda"

    # Optional VPC config (set to your VPC/subnets/SGs or omit)
    create_security_group = false
    vpc_config = {
      vpc_id             = "vpc-08586cd9f6ce3a905"
      subnet_ids         = ["subnet-0ffa21d23c30bbf14", "subnet-09e78cbbf83798d9a", "subnet-0071f6115ba604b19"]
      security_group_ids = ["sg-0ed6967b20d09fea2"]
    }

    # Scheduler configuration
    scheduler_role_arn = "arn:aws:iam::683918607581:role/service-role/Amazon_EventBridge_Scheduler_SFN_eb896e981c"

    schedule_name                = "monthly-adding-site-tables-producer-schedule"
    schedule_description         = "Trigger monthly-adding-site-tables-producer on a schedule"
    schedule_expression          = "cron(20 0 1 * ? *)"
    schedule_expression_timezone = "Asia/Tokyo"
    schedule_enabled             = true

    # Optional payload
    schedule_input = {}
  }
}
