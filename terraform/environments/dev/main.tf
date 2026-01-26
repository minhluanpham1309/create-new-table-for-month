variable "lambda_function_name_producer" {
  default = "MonthlyAddingSiteTablesProducer"
}
variable "lambda_function_name_consumer" {
  default = "MonthlyAddingSiteTablesConsumer"
}
variable "sns_topic_monthly_adding_site_tables_notifications" {
  default = "monthly-adding-site-tables-notifications"
}
variable "sfn_name_monthly_adding_site_tables_consumer" {
  default = "monthly-adding-site-tables-consumer"
}
module "heatmap_japan_dev" {
  source = "../../"

  # Basic configuration
  aws_region   = "ap-northeast-1"
  environment  = "dev"
  project_name = "heatmap-japan"

  # Network configuration - existing VPC
  vpc_id                     = "vpc-08586cd9f6ce3a905"
  subnet_ids                 = ["subnet-0ffa21d23c30bbf14", "subnet-09e78cbbf83798d9a", "subnet-0071f6115ba604b19"]
  allowed_security_group_ids = ["sg-01bac204cde449aee", "sg-06addf3041186f839", "sg-03b92aa686c2d348d"]
  # Valkey configuration for dev - single node for cost savings
  valkey_node_type                  = "cache.t4g.micro" # Smallest ARM-based instance
  valkey_num_cache_nodes            = 1                 # Single node to save cost
  valkey_engine_version             = "8.1"             # Latest Valkey version
  valkey_multi_az_enabled           = false             # Single AZ for dev
  valkey_at_rest_encryption_enabled = false             # Disable encryption for simplicity
  valkey_transit_encryption_enabled = false             # Disable encryption for simplicity
  valkey_snapshot_retention_limit   = 1                 # Minimal backup retention
  valkey_snapshot_window            = "03:00-04:00"
  valkey_maintenance_window         = "sun:04:00-sun:05:00"
  valkey_enable_cloudwatch_alarms   = true # No alarms for dev
  valkey_alarm_actions              = ["arn:aws:sns:ap-northeast-1:683918607581:alert-valkey"]
  valkey_memory_alarm_threshold     = 104857600 # 100 MB

  # Lambda functions configuration (if needed)
  monthly_adding_site_tables_producers = {
    # Lambda function configuration
    lambda_function_name = var.lambda_function_name_producer

    lambda_environment_variables = {
      SITE_CHUNK_DAYS = 21
      RDS_SECRET_NAME = "rds/db-test-private"
    }

    lambda_inline_policies = {
      "${var.lambda_function_name_producer}-lambda-role" = jsonencode({
        Version = "2012-10-17"
        Statement = [
          {
            Sid      = "ReadRDSSecrets"
            Effect   = "Allow"
            Action   = ["secretsmanager:GetSecretValue"]
            Resource = "arn:aws:secretsmanager:ap-northeast-1:683918607581:secret:rds/db-test-private*"
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
    
    # Secrets Manager End Point Security Group
    smg_end_point_sg_id = "sg-00ca8426775d6c9b3"

    # Scheduler configuration
    schedule_name = "monthly-adding-site-tables-producer-schedule"
    scheduler_inline_policies = {
      "invoke-lambda" = jsonencode({
        Version = "2012-10-17"
        Statement = [{
          Sid      = "InvokeLambdaFunction"
          Effect   = "Allow"
          Action   = ["lambda:InvokeFunction"]
          Resource = ["arn:aws:lambda:ap-northeast-1:683918607581:function:${var.lambda_function_name_producer}*"]
        }]
      })
    }

    schedule_retry_policy = {
      maximum_event_age_in_seconds = 900
      maximum_retry_attempts       = 3
    }
  }

  # monthly-adding-site-tables-consumer configuration (if needed)
  monthly_adding_site_tables_consumer = {
    # Lambda function configuration
    lambda_function_name = var.lambda_function_name_consumer

    lambda_environment_variables = {
      RDS_SECRET_NAME = "rds/db-test-private"
    }

    lambda_inline_policies = {
      "${var.lambda_function_name_consumer}-lambda-role" = jsonencode({
        Version = "2012-10-17"
        Statement = [
          {
            Sid      = "ReadRDSSecrets"
            Effect   = "Allow"
            Action   = ["secretsmanager:GetSecretValue"]
            Resource = "arn:aws:secretsmanager:ap-northeast-1:683918607581:secret:rds/db-test-private*"
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
    
    # Secrets Manager End Point Security Group
    smg_end_point_sg_id = "sg-00ca8426775d6c9b3"

    # Step Function configuration
    step_function_name = var.sfn_name_monthly_adding_site_tables_consumer
    step_function_inline_policies = {
      "invoke-lambda" = jsonencode({
        Version = "2012-10-17"
        Statement = [{
          Sid      = "InvokeLambdaFunction"
          Effect   = "Allow"
          Action   = ["lambda:InvokeFunction"]
          Resource = ["arn:aws:lambda:ap-northeast-1:683918607581:function:${var.lambda_function_name_consumer}*"]
        }]
      }),
      "publish-sns" = jsonencode({
        Version = "2012-10-17"
        Statement = [{
          Sid      = "PublishToSNSTopic"
          Effect   = "Allow"
          Action   = ["sns:Publish"]
          Resource = ["arn:aws:sns:ap-northeast-1:683918607581:${var.sns_topic_monthly_adding_site_tables_notifications}"]
        }]
      })
    }

    # SNS Topic configuration
    sns_topic_name          = var.sns_topic_monthly_adding_site_tables_notifications
    sns_display_name        = "Monthly Adding Site Tables Notifications"
    sns_subscription_emails = ["minhluanpham1309@gmail.com"]

    # Scheduler configuration
    schedule_name       = "monthly-adding-site-tables-consumer-schedule"
    schedule_expression = "cron(30 0 * * ? *)" # At 00:30 AM every day
    scheduler_inline_policies = {
      "execute_state_machine" = jsonencode({
        Version = "2012-10-17"
        Statement = [
          {
            Sid      = "StartStepFunctionExecution"
            Effect   = "Allow"
            Action   = ["states:StartExecution"]
            Resource = ["arn:aws:states:ap-northeast-1:683918607581:stateMachine:${var.sfn_name_monthly_adding_site_tables_consumer}"]
          }
        ]
      })
    }
  }
}
