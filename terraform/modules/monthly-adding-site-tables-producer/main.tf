# Reusable "monthly-adding-site-tables-producer" module (Lambda + EventBridge Scheduler)
locals {
  composed_lambda_env = merge(
    {
      ENVIRONMENT = var.environment
    },
    var.lambda_environment_variables
  )
}

module "lambda" {
  source = "../lambda-function"

  project_name = var.project_name

  function_name = var.lambda_function_name
  handler       = var.lambda_handler
  runtime       = var.lambda_runtime

  timeout       = var.lambda_timeout
  memory_size   = var.lambda_memory_size
  architectures = var.lambda_architectures

  filename         = var.lambda_filename
  source_code_hash = var.lambda_source_code_hash

  environment_variables = local.composed_lambda_env

  role_arn = var.lambda_role_arn

  create_security_group = var.create_security_group
  vpc_config            = var.vpc_config

  log_retention_in_days = var.lambda_log_retention_in_days
  tags                  = var.tags
}

module "schedule" {
  source = "../eventbridge-scheduler"

  project_name = var.project_name

  name                        = var.schedule_name
  rule_name                   = var.schedule_rule_name
  description                 = var.schedule_description
  schedule_expression         = var.schedule_expression
  schedule_expression_timezone = var.schedule_expression_timezone
  enabled                     = var.schedule_enabled
  scheduler_role_arn          = var.scheduler_role_arn

  target = {
    type  = "lambda"
    arn   = module.lambda.function_arn
    input = var.schedule_input
  }
}
