variable "lambda_function_name" {
  default = "MonthlyAddingSiteTablesProducer"
}
module "heatmap_japan_dev" {
  source = "../../"

  # Basic configuration
  aws_region   = "ap-northeast-1"
  environment  = "dev"
  project_name = "heatmap-japan"

  # Network configuration - existing VPC
  vpc_id                    = "vpc-08586cd9f6ce3a905"
  subnet_ids                = ["subnet-0ffa21d23c30bbf14", "subnet-09e78cbbf83798d9a", "subnet-0071f6115ba604b19"]
  allowed_security_group_ids = ["sg-01bac204cde449aee","sg-06addf3041186f839","sg-03b92aa686c2d348d"]
  # Valkey configuration for dev - single node for cost savings
  valkey_node_type                       = "cache.t4g.micro"   # Smallest ARM-based instance
  valkey_num_cache_nodes                 = 1                   # Single node to save cost
  valkey_engine_version                  = "8.1"               # Latest Valkey version
  valkey_multi_az_enabled                = false               # Single AZ for dev
  valkey_at_rest_encryption_enabled      = false               # Disable encryption for simplicity
  valkey_transit_encryption_enabled      = false               # Disable encryption for simplicity
  valkey_snapshot_retention_limit        = 1                   # Minimal backup retention
  valkey_snapshot_window                 = "03:00-04:00"
  valkey_maintenance_window              = "sun:04:00-sun:05:00"
  valkey_enable_cloudwatch_alarms        = true               # No alarms for dev
  valkey_alarm_actions = ["arn:aws:sns:ap-northeast-1:683918607581:alert-valkey"]

  # Lambda functions configuration (if needed)
  monthly_adding_site_tables_producers = {
    # Lambda function configuration
    lambda_function_name = var.lambda_function_name

    lambda_environment_variables = {
      SITE_CHUNK_DAYS = 21
      RDS_SECRET_NAME = "rds/db-test-private"
    }

    lambda_inline_policies = {
      "${var.lambda_function_name}-lambda-role" = jsonencode({
        Version = "2012-10-17"
        Statement = [
          {
            Sid      = "ReadRDSSecrets"
            Effect   = "Allow"
            Action   = ["secretsmanager:GetSecretValue"]
            Resource = "arn:aws:secretsmanager:ap-northeast-1:683918607581:secret:rds/db-test-private*"
          },{
            Sid    = "CloudWatchLogsAccess"
            Effect = "Allow"
            Action = [
              "logs:CreateLogGroup",
              "logs:CreateLogStream",
              "logs:PutLogEvents"
            ]
            Resource = [
              "arn:aws:logs:ap-northeast-1:683918607581:*"
            ]
          }
        ]
      })
    }

    # VPC config
    create_security_group = true
    vpc_config = {
      vpc_id             = "vpc-08586cd9f6ce3a905"
      subnet_ids         = ["subnet-0ffa21d23c30bbf14", "subnet-09e78cbbf83798d9a", "subnet-0071f6115ba604b19"]
      security_group_ids = []
    }

    # RDS Security Group
    rds_security_group_id = "sg-0ec24edb38ce58304"

    # Scheduler configuration
    schedule_name                = "monthly-adding-site-tables-producer-schedule"
    scheduler_inline_policies = {
      "invoke-lambda" = jsonencode({
        Version = "2012-10-17"
        Statement = [{
          Sid      = "InvokeLambdaFunction"
          Effect   = "Allow"
          Action   = ["lambda:InvokeFunction"]
          Resource = ["arn:aws:lambda:ap-northeast-1:683918607581:function:${var.lambda_function_name}*"]
        }]
      })
    }

    schedule_retry_policy = {
      maximum_event_age_in_seconds = 900
      maximum_retry_attempts       = 3
    }
  }
}
