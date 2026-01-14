# Locals
locals {
  # Auto-detect: create roles if ARN not provided
  create_lambda_role    = var.lambda_role_arn == null
  create_scheduler_role = var.scheduler_role_arn == null

  # Role names (only used when creating roles)
  lambda_role_name    = "${var.project_name}-${var.lambda_function_name}-lambda"
  scheduler_role_name = "${var.project_name}-${var.lambda_function_name}-scheduler"

  # Effective ARNs (use created role ARN or provided ARN)
  lambda_role_arn    = local.create_lambda_role ? module.lambda_role[0].role_arn : var.lambda_role_arn
  scheduler_role_arn = local.create_scheduler_role ? module.scheduler_role[0].role_arn : var.scheduler_role_arn
}

# Lambda Execution Role
module "lambda_role" {
  count  = local.create_lambda_role ? 1 : 0
  source = "../iam-role"

  role_name          = local.lambda_role_name
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })

  inline_policies     = var.lambda_inline_policies
  managed_policy_arns = var.vpc_config != null ? ["arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"] : [],

  tags = var.tags
}

# Scheduler Role
module "scheduler_role" {
  count  = local.create_scheduler_role ? 1 : 0
  source = "../iam-role"

  role_name          = local.scheduler_role_name
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "scheduler.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })

  inline_policies = var.scheduler_inline_policies
  tags                = var.tags
}

# Lambda Function
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

  environment_variables = var.lambda_environment_variables

  role_arn = local.lambda_role_arn

  create_security_group = var.create_security_group
  vpc_config            = var.vpc_config

  log_retention_in_days = var.lambda_log_retention_in_days
  tags                  = var.tags
}

module "schedule" {
  source = "../eventbridge-scheduler"

  project_name = var.project_name

  name                         = var.schedule_name
  description                  = var.schedule_description
  schedule_expression          = var.schedule_expression
  schedule_expression_timezone = var.schedule_expression_timezone
  enabled                      = var.schedule_enabled
  scheduler_role_arn           = local.scheduler_role_arn

  target = {
    type  = "lambda"
    arn   = module.lambda.function_arn
    input = var.schedule_input
  }
}

