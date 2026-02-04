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

  role_arn = var.lambda_role_arn

  create_security_group = var.create_security_group
  vpc_config            = var.vpc_config
  rds_security_group_id = var.rds_security_group_id
  smg_end_point_sg_id   = var.smg_end_point_sg_id

  log_retention_in_days = var.lambda_log_retention_in_days
  tags                  = var.tags
}

# Step Functions State Machine
module "step_function" {
  source = "../step-functions"

  state_name = var.step_function_name
  role_arn   = var.step_function_role_arn
  definition = jsonencode({
    "Comment" : "Minimal state machine",
    "StartAt" : "Pass",
    "States" : {
      "Pass" : {
        "Type" : "Pass",
        "End" : true
      }
    }
  })

  tags = var.tags
}

# SNS Topic
module "sns_topic" {
  source = "../sns"

  topic_name          = var.sns_topic_name
  display_name        = var.sns_display_name
  subscription_emails = var.sns_subscription_emails

  tags = var.tags
}

# EventBridge Scheduler
module "schedule" {
  source = "../eventbridge-scheduler"

  project_name = var.project_name

  name                         = var.schedule_name
  description                  = var.schedule_description
  schedule_expression          = var.schedule_expression
  schedule_expression_timezone = var.schedule_expression_timezone
  enabled                      = var.schedule_enabled
  scheduler_role_arn           = var.scheduler_role_arn
  retry_policy                 = var.schedule_retry_policy

  target = {
    type  = "step_function"
    arn   = module.step_function.state_machine_arn
    input = var.schedule_input
  }
}