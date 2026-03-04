variable "project_name" {
  description = "Project name used as prefix for resources"
  type        = string
}

variable "tags" {
  description = "Additional tags"
  type        = map(string)
  default     = {}
}

# ============================================================================
# Lambda Configuration
# ============================================================================

variable "lambda_function_name" {
  description = "Lambda function name"
  type        = string
}

variable "lambda_handler" {
  description = "Lambda handler"
  type        = string
  default     = "lambda_function.lambda_handler"
}

variable "lambda_runtime" {
  description = "Lambda runtime"
  type        = string
  default     = "python3.11"
}

variable "lambda_timeout" {
  description = "Lambda timeout (seconds)"
  type        = number
  default     = 300
}

variable "lambda_memory_size" {
  description = "Lambda memory size (MB)"
  type        = number
  default     = 512
}

variable "lambda_architectures" {
  description = "Lambda architectures"
  type        = list(string)
  default     = ["x86_64"]
}

variable "lambda_environment_variables" {
  description = "Environment variables for lambda"
  type        = map(string)
  default     = {}
}

variable "lambda_role_arn" {
  description = "IAM role ARN for Lambda function"
  type        = string
}

variable "lambda_log_retention_in_days" {
  description = "CloudWatch log retention for lambda"
  type        = number
  default     = 90
}

variable "lambda_alias" {
  description = "Lambda alias for versioning"
  type        = string
  default     = null
}

# ============================================================================
# VPC Configuration
# ============================================================================

variable "vpc_config" {
  description = "VPC config for lambda"
  type = object({
    vpc_id             = string
    subnet_ids         = list(string)
    security_group_ids = list(string)
  })
  default = null
}

variable "create_security_group" {
  description = "Whether to create a security group for lambda when vpc_config is set"
  type        = bool
  default     = false
}

variable "rds_security_group_id" {
  description = "RDS security group ID to allow Lambda access"
  type        = string
  default     = null
}

variable "smg_end_point_sg_id" {
  description = "Secrets Manager VPC endpoint security group ID"
  type        = string
  default     = null
}

variable "valkey_security_group_id" {
  description = "Valkey security group ID to allow Lambda access"
  type        = string
  default     = null
}

variable "valkey_port" {
  description = "Valkey port"
  type        = number
  default     = 6379
}

# ============================================================================
# EventBridge Scheduler Configuration (Optional)
# ============================================================================

variable "schedule_name" {
  description = "Logical schedule name (will be prefixed by project_name)"
  type        = string
  default     = null
}

variable "schedule_description" {
  description = "Schedule description"
  type        = string
  default     = "Scheduled execution of move-data-to-mysql Lambda"
}

variable "schedule_expression" {
  description = "Schedule expression (cron or rate)"
  type        = string
  default     = "cron(0 2 * * ? *)" # Daily at 2 AM UTC
}

variable "schedule_expression_timezone" {
  description = "Schedule timezone"
  type        = string
  default     = "Asia/Tokyo"
}

variable "schedule_enabled" {
  description = "Enable schedule"
  type        = bool
  default     = true
}

variable "schedule_input" {
  description = "Optional input payload for the Lambda function"
  type        = any
  default     = null
}

variable "scheduler_role_arn" {
  description = "IAM role ARN for EventBridge Scheduler"
  type        = string
  default     = null
}

variable "schedule_retry_policy" {
  description = "Retry policy for the schedule"
  type = object({
    maximum_event_age_in_seconds = number
    maximum_retry_attempts       = number
  })
  default = {
    maximum_event_age_in_seconds = 900
    maximum_retry_attempts       = 3
  }
}

variable "netty_redis_sg_id" {
    description = "Security group ID for Netty Redis to allow Lambda access"
    type        = string
    default     = null
}
