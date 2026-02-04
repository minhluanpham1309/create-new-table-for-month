# ============================================================================
# DELETE HEAT MAP CACHE MODULE - VARIABLES
# ============================================================================

variable "project_name" {
  description = "Project name used as prefix for resources"
  type        = string
}

variable "tags" {
  description = "Additional tags to apply to all resources"
  type        = map(string)
  default     = {}
}

# ============================================================================
# LAMBDA CONFIGURATION
# ============================================================================

variable "lambda_function_name" {
  description = "Lambda function name (will be prefixed with project_name)"
  type        = string
  default     = "DeleteHeatMapCache"
}

variable "lambda_handler" {
  description = "Lambda handler (e.g., 'lambda_function.lambda_handler')"
  type        = string
  default     = "lambda_function.lambda_handler"
}

variable "lambda_runtime" {
  description = "Lambda runtime (e.g., 'python3.11')"
  type        = string
  default     = "python3.11"
}

variable "lambda_timeout" {
  description = "Lambda timeout in seconds"
  type        = number
  default     = 300
}

variable "lambda_memory_size" {
  description = "Lambda memory size in MB"
  type        = number
  default     = 256
}

variable "lambda_architectures" {
  description = "Lambda architectures (e.g., ['x86_64'] or ['arm64'])"
  type        = list(string)
  default     = ["x86_64"]
}

variable "lambda_environment_variables" {
  description = "Environment variables for Lambda function"
  type        = map(string)
  default     = {}
}

variable "lambda_role_arn" {
  description = "IAM role ARN for Lambda function"
  type        = string
}

variable "lambda_log_retention_in_days" {
  description = "CloudWatch log retention for Lambda in days"
  type        = number
  default     = 7
}

# ============================================================================
# VPC CONFIGURATION
# ============================================================================

variable "vpc_config" {
  description = "VPC configuration for Lambda function"
  type = object({
    vpc_id             = string
    subnet_ids         = list(string)
    security_group_ids = list(string)
  })
  default = null
}

variable "create_security_group" {
  description = "Whether to create a security group for Lambda when vpc_config is set"
  type        = bool
  default     = false
}

variable "rds_security_group_id" {
  description = "RDS Security Group ID to allow Lambda access. If provided, will create ingress rule."
  type        = string
  default     = null
}

variable "smg_end_point_sg_id" {
  description = "Secrets Manager VPC endpoint security group ID to allow Lambda access. If provided, will create ingress rule."
  type        = string
  default     = null
}

# ============================================================================
# EVENTBRIDGE SCHEDULER CONFIGURATION
# ============================================================================

variable "schedule_name" {
  description = "EventBridge schedule name (will be prefixed with project_name)"
  type        = string
  default     = "delete-cache-schedule"
}

variable "schedule_description" {
  description = "Description for the EventBridge schedule"
  type        = string
  default     = "Schedule for deleting heat map cache data"
}

variable "schedule_expression" {
  description = "Schedule expression (e.g., 'rate(1 day)' or 'cron(0 2 * * ? *)')"
  type        = string
  default     = "cron(0 2 * * ? *)" # Run daily at 2:00 AM UTC
}

variable "schedule_expression_timezone" {
  description = "Timezone for the schedule expression"
  type        = string
  default     = "Asia/Tokyo"
}

variable "schedule_enabled" {
  description = "Whether to enable the EventBridge schedule"
  type        = bool
  default     = true
}

variable "schedule_input" {
  description = "Optional input payload for the Lambda target"
  type        = any
  default     = null
}

variable "scheduler_role_arn" {
  description = "IAM role ARN for EventBridge Scheduler"
  type        = string
}

variable "schedule_retry_policy" {
  description = "Retry policy configuration for the EventBridge schedule"
  type = object({
    maximum_event_age_in_seconds = number
    maximum_retry_attempts       = number
  })
  default = {
    maximum_event_age_in_seconds = 3600
    maximum_retry_attempts       = 3
  }
}
