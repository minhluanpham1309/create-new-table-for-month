variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "ap-northeast-1"
}

variable "environment" {
  description = "Environment name (dev, prod)"
  type        = string
}

variable "project_name" {
  description = "Project name"
  type        = string
  default     = "heatmap-japan"
}

variable "tags" {
  description = "Additional tags"
  type        = map(string)
  default     = {}
}

# Step Function variables (unified object map)
variable "step_functions" {
  description = "Map of Step Functions to create"
  type = map(object({
    name                  = string
    definition            = string
    tags                  = optional(map(string))
    state_machine_type    = optional(string, "STANDARD")
    enable_logging        = optional(bool, true)
    log_level             = optional(string, "OFF")
    log_retention_in_days = optional(number, 7)
    execution_role_arn    = optional(string)
  }))
  default = {}
}

# Monthly Adding Site Tables Producer (Lambda + EventBridge Scheduler)
variable "monthly_adding_site_tables_producers" {
  description = "Configuration for monthly-adding-site-tables-producer"
  type = object({
    # Lambda
    lambda_function_name         = string
    lambda_handler               = optional(string, "lambda_function.lambda_handler")
    lambda_runtime               = optional(string, "python3.11")
    lambda_timeout               = optional(number, 900)
    lambda_memory_size           = optional(number, 256)
    lambda_architectures         = optional(list(string), ["x86_64"])
    lambda_environment_variables = optional(map(string), {})
    lambda_log_retention_in_days = optional(number, 7)

    # Lambda IAM Role (Auto-create if null)
    lambda_role_arn           = optional(string, null)
    lambda_inline_policies    = optional(map(string), {})

    # Optional VPC
    vpc_config = optional(object({
      vpc_id             = string
      subnet_ids         = list(string)
      security_group_ids = list(string)
    }))
    create_security_group = optional(bool, false)

    # EventBridge Scheduler
    schedule_name                = string
    schedule_description         = optional(string, "Trigger monthly-adding-site-tables-producer on a schedule")
    schedule_expression          = optional(string, "cron(0 9 * * ? *)")
    schedule_expression_timezone = optional(string, "Asia/Tokyo")
    schedule_enabled             = optional(bool, true)
    schedule_input               = optional(any, {})

    # Scheduler IAM Role (Auto-create if null)
    scheduler_role_arn           = optional(string, null)
    scheduler_inline_policies    = optional(map(string), {})

    # Tags
    tags = optional(map(string), {})
  })

  nullable = true
  default  = null
}
