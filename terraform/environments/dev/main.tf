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
variable "lambda_function_name_delete_heat_map_cache" {
  default = "DeleteHeatMapCache"
}

# Locals for reusable resources (ARNs)
locals {
  # AWS Configuration
  aws_region  = "ap-northeast-1"
  aws_account = "683918607581"
  aws_shorthand = "${local.aws_region}:${local.aws_account}" # shorthand

  # Resource ARNs
  rds_secret_arn              = "arn:aws:secretsmanager:${local.aws_shorthand}:secret:rds/db-test-private*"
  producer_lambda_arn         = "arn:aws:lambda:${local.aws_shorthand}:function:${var.lambda_function_name_producer}*"
  consumer_lambda_arn         = "arn:aws:lambda:${local.aws_shorthand}:function:${var.lambda_function_name_consumer}*"
  delete_lambda_arn         = "arn:aws:lambda:${local.aws_shorthand}:function:${var.lambda_function_name_delete_heat_map_cache}*"
  sns_topic_arn               = "arn:aws:sns:${local.aws_shorthand}:${var.sns_topic_monthly_adding_site_tables_notifications}"
  step_functions_state_machine_arn = "arn:aws:states:${local.aws_shorthand}:stateMachine:${var.sfn_name_monthly_adding_site_tables_consumer}"

  # ===================================================================
  # IAM Policies organized by Service Type
  # ===================================================================
  
  # Lambda Function Policies
  lambda_policies = {
    # Policy: Read RDS Secrets (used by both producer and consumer Lambda)
    "read-rds-secrets" = jsonencode({
      Version = "2012-10-17"
      Statement = [{
        Sid      = "ReadRDSSecrets"
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = local.rds_secret_arn
      }]
    })
  }

  # EventBridge Scheduler Policies
  eventbridge_scheduler_policies = {
    # Policy: Invoke Lambda (used by producer scheduler)
    "invoke-lambda" = jsonencode({
      Version = "2012-10-17"
      Statement = [{
        Sid      = "InvokeLambdaFunction"
        Effect   = "Allow"
        Action   = ["lambda:InvokeFunction"]
        Resource = [local.producer_lambda_arn , local.delete_lambda_arn]
      }]
    })
    
    # Policy: Execute Step Functions (used by consumer scheduler)
    "execute-state-machine" = jsonencode({
      Version = "2012-10-17"
      Statement = [{
        Sid      = "StartStepFunctionExecution"
        Effect   = "Allow"
        Action   = ["states:StartExecution"]
        Resource = [local.step_functions_state_machine_arn]
      }]
    })
  }

  # Step Functions Policies
  step_functions_policies = {
    # Policy: Invoke Lambda (used by consumer step function)
    "invoke-lambda" = jsonencode({
      Version = "2012-10-17"
      Statement = [{
        Sid      = "InvokeLambdaFunction"
        Effect   = "Allow"
        Action   = ["lambda:InvokeFunction"]
        Resource = [local.consumer_lambda_arn]
      }]
    })
    
    # Policy: Publish to SNS (used by consumer step function)
    "publish-sns" = jsonencode({
      Version = "2012-10-17"
      Statement = [{
        Sid      = "PublishToSNSTopic"
        Effect   = "Allow"
        Action   = ["sns:Publish"]
        Resource = [local.sns_topic_arn]
      }]
    })
  }
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
    
    lambda_inline_policies = local.lambda_policies
    lambda_log_retention_in_days = 90

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
      "invoke-lambda" = local.eventbridge_scheduler_policies["invoke-lambda"]
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

    lambda_inline_policies = local.lambda_policies
    lambda_log_retention_in_days = 90

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
    step_function_inline_policies = local.step_functions_policies

    # SNS Topic configuration
    sns_topic_name          = var.sns_topic_monthly_adding_site_tables_notifications
    sns_display_name        = "Monthly Adding Site Tables Notifications"
    sns_subscription_emails = ["minhluanpham1309@gmail.com"]

    # Scheduler configuration
    schedule_name       = "monthly-adding-site-tables-consumer-schedule"
    schedule_expression = "cron(30 0 * * ? *)" # At 00:30 AM every day
    scheduler_inline_policies = {
      "execute-state-machine" = local.eventbridge_scheduler_policies["execute-state-machine"]
    }
    
    schedule_retry_policy = {
      maximum_event_age_in_seconds = 900
      maximum_retry_attempts       = 3
    }
  }
  
  # Lambda functions configuration (if needed)
  delete_heat_map_cache = {
    # Lambda function configuration
    lambda_function_name = var.lambda_function_name_delete_heat_map_cache

    lambda_environment_variables = {
      SITE_CHUNK_DAYS = 21
      RDS_SECRET_NAME = "rds/db-test-private"
    }
    
    lambda_inline_policies = local.lambda_policies
    lambda_log_retention_in_days = 90

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
    schedule_name = "delete-heat-map-cache-schedule"
    schedule_expression = "cron(0 0 1 * ? *)"
    scheduler_inline_policies = {
      "invoke-lambda" = local.eventbridge_scheduler_policies["invoke-lambda"]
    }

    schedule_retry_policy = {
      maximum_event_age_in_seconds = 900
      maximum_retry_attempts       = 3
    }
  }
}
