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

# Commented out - Valkey related variables
# variable "vpc_id" {
#   description = "Existing VPC ID"
#   type        = string
# }
# 
# variable "subnet_ids" {
#   description = "Existing subnet IDs for Valkey"
#   type        = list(string)
# }
# 
# variable "allowed_security_group_ids" {
#   description = "Security group IDs of EC2 instances allowed to access Valkey"
#   type        = list(string)
#   default     = []
# }

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
  description = "Map of monthly-adding-site-tables-producer module instances"
  type = object({
    # Lambda
    lambda_function_name         = string
    lambda_handler               = optional(string, "lambda_function.lambda_handler")
    lambda_runtime               = optional(string, "python3.11")
    lambda_timeout               = optional(number, 900)
    lambda_memory_size           = optional(number, 256)
    lambda_architectures         = optional(list(string), ["x86_64"])
    lambda_filename              = optional(string, null)
    lambda_source_code_hash      = optional(string, null)
    lambda_environment_variables = optional(map(string), {})
    lambda_role_arn              = string
    lambda_log_retention_in_days = optional(number, 7)

    # Optional VPC
    vpc_config = optional(object({
      vpc_id             = string
      subnet_ids         = list(string)
      security_group_ids = list(string)
    }))
    create_security_group = optional(bool, false)

    # Scheduler
    schedule_name                = string
    schedule_description         = optional(string, "Trigger monthly-adding-site-tables-producer on a schedule")
    schedule_expression          = optional(string, "cron(0 9 * * ? *)")
    schedule_expression_timezone = optional(string, "Asia/Tokyo")
    schedule_enabled             = optional(bool, true)
    scheduler_role_arn           = string
    schedule_input               = optional(any, {})

    tags = optional(map(string), {})
  })

  nullable = true
  default  = null
}
