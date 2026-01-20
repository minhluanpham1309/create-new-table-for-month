# Lambda Execution Role
module "lambda_role" {
  source = "../iam-role"

  role_name          = "${var.lambda_function_name}-lambda"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })

  inline_policies     = var.lambda_inline_policies
  managed_policy_arns = var.vpc_config != null ? ["arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"] : []

  tags = var.tags
}

# Scheduler Role
module "scheduler_role" {
  source = "../iam-role"

  role_name          = "${var.lambda_function_name}-scheduler"
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

  environment_variables = var.lambda_environment_variables

  role_arn = module.lambda_role.role_arn

  create_security_group = var.create_security_group
  vpc_config            = var.vpc_config
  rds_security_group_id = var.rds_security_group_id

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
  scheduler_role_arn           = module.scheduler_role.role_arn

  target = {
    type  = "lambda"
    arn   = module.lambda.function_arn
    input = var.schedule_input
  }
  retry_policy = var.schedule_retry_policy
}

