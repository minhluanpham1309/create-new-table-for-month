terraform {
  required_version = ">= 1.5"
  
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.29.0"
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

# # Valkey Module
# module "valkey" {
#   source = "./modules/valkey"
#
#   project_name               = var.project_name
#   environment                = var.environment
#   vpc_id                    = var.vpc_id
#   subnet_ids                = var.subnet_ids
#   allowed_security_group_ids = var.allowed_security_group_ids
#
#   # Valkey configuration
#   node_type           = var.valkey_node_type
#   num_cache_nodes     = var.valkey_num_cache_nodes
#   engine_version      = var.valkey_engine_version
#   multi_az_enabled    = var.valkey_multi_az_enabled
#
#   # Security
#   at_rest_encryption_enabled = var.valkey_at_rest_encryption_enabled
#   transit_encryption_enabled = var.valkey_transit_encryption_enabled
#
#   # Backup
#   snapshot_retention_limit = var.valkey_snapshot_retention_limit
#   snapshot_window         = var.valkey_snapshot_window
#   maintenance_window      = var.valkey_maintenance_window
#
#   # Monitoring
#   enable_cloudwatch_alarms = var.valkey_enable_cloudwatch_alarms
#
#   tags = var.tags
# }

# Lambda Functions Module
module "lambda_functions" {
  source                = "./modules/lambda-function"
  for_each              = var.lambda_functions

  project_name          = var.project_name
  function_name         = each.value.function_name
  handler               = each.value.handler
  runtime               = each.value.runtime

  timeout               = each.value.timeout
  memory_size           = each.value.memory_size
  environment_variables = each.value.environment_variables
  role_arn              = try(each.value.role_arn, null)

  create_security_group = try(each.value.create_security_group, false)
  vpc_config            = each.value.vpc_config

  tags = var.tags
}

# Step Function Module
module "step_function" {
  source   = "./modules/step-functions"
  for_each = var.step_functions

  project_name         = var.project_name
  name                 = each.value.name
  definition           = each.value.definition

  state_machine_type   = each.value.state_machine_type
  enable_logging       = each.value.enable_logging
  log_level            = each.value.log_level
  log_retention_in_days = each.value.log_retention_in_days
  execution_role_arn    = try(each.value.execution_role_arn, null)

  tags                 = var.tags
}

# # EventBridge Rule Module
# module "eventbridge_rule" {
#   source   = "./modules/eventbridge-rule"
#   for_each = var.eventbridge_rules
#
#   project_name                  = var.project_name
#   name                          = each.value.name
#   description                   = each.value.description
#   schedule_expression           = each.value.schedule_expression
#   enabled                       = each.value.enabled
#   schedule_expression_timezone  = try(each.value.time_zone, "UTC")
#   scheduler_retry_policy = try(each.value.scheduler_retry_policy, {})
#
#   targets = each.value.targets
#
#   tags = each.value.tags != null ? each.value.tags : var.tags
# }
