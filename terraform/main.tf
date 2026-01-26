terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = var.project_name
      Stage       = var.environment
      ManagedBy   = "terraform"
      ServiceName = "Heatmap"
      FeatureName = "Heatmap"
    }
  }
}

# Valkey Module
module "valkey" {
  source = "./modules/valkey"

  project_name               = var.project_name
  environment                = var.environment
  vpc_id                     = var.vpc_id
  subnet_ids                 = var.subnet_ids
  allowed_security_group_ids = var.allowed_security_group_ids

  # Valkey configuration
  node_type        = var.valkey_node_type
  num_cache_nodes  = var.valkey_num_cache_nodes
  engine_version   = var.valkey_engine_version
  multi_az_enabled = var.valkey_multi_az_enabled

  # Security
  at_rest_encryption_enabled = var.valkey_at_rest_encryption_enabled
  transit_encryption_enabled = var.valkey_transit_encryption_enabled

  # Backup
  snapshot_retention_limit = var.valkey_snapshot_retention_limit
  snapshot_window          = var.valkey_snapshot_window
  maintenance_window       = var.valkey_maintenance_window

  # Monitoring
  enable_cloudwatch_alarms = var.valkey_enable_cloudwatch_alarms
  alarm_actions            = var.valkey_alarm_actions
  memory_alarm_threshold   = var.valkey_memory_alarm_threshold

  tags = var.tags
}

# Monthly Adding Site Tables Producer (Lambda + EventBridge Scheduler)
module "monthly_adding_site_tables_producer" {
  source = "./modules/monthly-adding-site-tables-producer"
  count  = var.monthly_adding_site_tables_producers == null ? 0 : 1

  project_name = var.project_name

  lambda_function_name         = var.monthly_adding_site_tables_producers.lambda_function_name
  lambda_handler               = var.monthly_adding_site_tables_producers.lambda_handler
  lambda_runtime               = var.monthly_adding_site_tables_producers.lambda_runtime
  lambda_timeout               = var.monthly_adding_site_tables_producers.lambda_timeout
  lambda_memory_size           = var.monthly_adding_site_tables_producers.lambda_memory_size
  lambda_architectures         = var.monthly_adding_site_tables_producers.lambda_architectures
  lambda_environment_variables = var.monthly_adding_site_tables_producers.lambda_environment_variables
  lambda_log_retention_in_days = var.monthly_adding_site_tables_producers.lambda_log_retention_in_days

  lambda_inline_policies = var.monthly_adding_site_tables_producers.lambda_inline_policies

  # VPC
  vpc_config            = try(var.monthly_adding_site_tables_producers.vpc_config, null)
  create_security_group = var.monthly_adding_site_tables_producers.create_security_group
  rds_security_group_id = var.monthly_adding_site_tables_producers.rds_security_group_id
  smg_end_point_sg_id   = var.monthly_adding_site_tables_producers.smg_end_point_sg_id

  # EventBridge Scheduler
  schedule_name                = var.monthly_adding_site_tables_producers.schedule_name
  schedule_description         = var.monthly_adding_site_tables_producers.schedule_description
  schedule_expression          = var.monthly_adding_site_tables_producers.schedule_expression
  schedule_expression_timezone = var.monthly_adding_site_tables_producers.schedule_expression_timezone
  schedule_enabled             = var.monthly_adding_site_tables_producers.schedule_enabled
  schedule_input               = var.monthly_adding_site_tables_producers.schedule_input

  scheduler_inline_policies = var.monthly_adding_site_tables_producers.scheduler_inline_policies
  schedule_retry_policy     = var.monthly_adding_site_tables_producers.schedule_retry_policy

  tags = merge(var.tags, try(var.monthly_adding_site_tables_producers.tags, {}))
}

# Monthly Adding Site Tables Producer (Lambda + EventBridge Scheduler)
module "monthly_adding_site_tables_consumer" {
  source = "./modules/monthly-adding-site-tables-consumer"
  count  = var.monthly_adding_site_tables_consumer == null ? 0 : 1

  project_name = var.project_name

  lambda_function_name         = var.monthly_adding_site_tables_consumer.lambda_function_name
  lambda_handler               = var.monthly_adding_site_tables_consumer.lambda_handler
  lambda_runtime               = var.monthly_adding_site_tables_consumer.lambda_runtime
  lambda_timeout               = var.monthly_adding_site_tables_consumer.lambda_timeout
  lambda_memory_size           = var.monthly_adding_site_tables_consumer.lambda_memory_size
  lambda_architectures         = var.monthly_adding_site_tables_consumer.lambda_architectures
  lambda_environment_variables = var.monthly_adding_site_tables_consumer.lambda_environment_variables
  lambda_log_retention_in_days = var.monthly_adding_site_tables_consumer.lambda_log_retention_in_days

  lambda_inline_policies = var.monthly_adding_site_tables_consumer.lambda_inline_policies

  # VPC
  vpc_config            = try(var.monthly_adding_site_tables_consumer.vpc_config, null)
  create_security_group = var.monthly_adding_site_tables_consumer.create_security_group
  rds_security_group_id = var.monthly_adding_site_tables_consumer.rds_security_group_id
  smg_end_point_sg_id   = var.monthly_adding_site_tables_consumer.smg_end_point_sg_id 

  # Step Function
  step_function_name            = var.monthly_adding_site_tables_consumer.step_function_name
  step_function_inline_policies = var.monthly_adding_site_tables_consumer.step_function_inline_policies

  # SNS Configuration
  sns_topic_name          = var.monthly_adding_site_tables_consumer.sns_topic_name
  sns_display_name        = var.monthly_adding_site_tables_consumer.sns_display_name
  sns_subscription_emails = var.monthly_adding_site_tables_consumer.sns_subscription_emails

  # EventBridge Scheduler
  schedule_name                = var.monthly_adding_site_tables_consumer.schedule_name
  schedule_description         = var.monthly_adding_site_tables_consumer.schedule_description
  schedule_expression          = var.monthly_adding_site_tables_consumer.schedule_expression
  schedule_expression_timezone = var.monthly_adding_site_tables_consumer.schedule_expression_timezone
  schedule_enabled             = var.monthly_adding_site_tables_consumer.schedule_enabled
  schedule_input               = var.monthly_adding_site_tables_consumer.schedule_input

  scheduler_inline_policies = var.monthly_adding_site_tables_consumer.scheduler_inline_policies

  tags = merge(var.tags, try(var.monthly_adding_site_tables_consumer.tags, {}))
}
