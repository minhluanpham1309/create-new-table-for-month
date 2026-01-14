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

# Step Function Module
# module "step_function" {
#   source   = "./modules/step-functions"
#   for_each = var.step_functions
#
#   project_name         = var.project_name
#   name                 = each.value.name
#   definition           = each.value.definition
#
#   state_machine_type   = each.value.state_machine_type
#   enable_logging       = each.value.enable_logging
#   log_level            = each.value.log_level
#   log_retention_in_days = each.value.log_retention_in_days
#   execution_role_arn    = try(each.value.execution_role_arn, null)
#
#   tags                 = var.tags
# }


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
  lambda_filename              = var.monthly_adding_site_tables_producers.lambda_filename
  lambda_source_code_hash      = var.monthly_adding_site_tables_producers.lambda_source_code_hash
  lambda_environment_variables = var.monthly_adding_site_tables_producers.lambda_environment_variables
  lambda_role_arn              = var.monthly_adding_site_tables_producers.lambda_role_arn
  lambda_log_retention_in_days = var.monthly_adding_site_tables_producers.lambda_log_retention_in_days

  vpc_config            = try(var.monthly_adding_site_tables_producers.vpc_config, null)
  create_security_group = var.monthly_adding_site_tables_producers.create_security_group

  schedule_name                = var.monthly_adding_site_tables_producers.schedule_name
  schedule_description         = var.monthly_adding_site_tables_producers.schedule_description
  schedule_expression          = var.monthly_adding_site_tables_producers.schedule_expression
  schedule_expression_timezone = var.monthly_adding_site_tables_producers.schedule_expression_timezone
  schedule_enabled             = var.monthly_adding_site_tables_producers.schedule_enabled
  scheduler_role_arn           = var.monthly_adding_site_tables_producers.scheduler_role_arn
  schedule_input               = var.monthly_adding_site_tables_producers.schedule_input

  tags = merge(var.tags, try(var.monthly_adding_site_tables_producers.tags, {}))
}
