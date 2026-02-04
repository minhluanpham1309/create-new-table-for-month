# ============================================================================
# DELETE CACHE EXAMPLE - VARIABLES
# ============================================================================

variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "ap-northeast-1"
}

variable "project_name" {
  description = "Project name"
  type        = string
  default     = "heatmap-japan"
}

variable "environment" {
  description = "Environment name"
  type        = string
  default     = "dev"
}

variable "tags" {
  description = "Common tags"
  type        = map(string)
  default = {
    Project     = "HeatMap"
    ManagedBy   = "Terraform"
    Environment = "dev"
  }
}

# ============================================================================
# LAMBDA CONFIGURATION
# ============================================================================

variable "lambda_function_name" {
  description = "Lambda function name"
  type        = string
  default     = "DeleteHeatMapCache"
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
  description = "Lambda architectures"
  type        = list(string)
  default     = ["x86_64"]
}

variable "lambda_log_retention_in_days" {
  description = "Lambda log retention in days"
  type        = number
  default     = 7
}

# ============================================================================
# CACHE CONFIGURATION
# ============================================================================

variable "cache_type" {
  description = "Type of cache to delete (redis, elasticache, memcached)"
  type        = string
  default     = "redis"
}

variable "redis_endpoint" {
  description = "Redis endpoint URL"
  type        = string
  default     = "localhost:6379"
}

variable "log_level" {
  description = "Log level for Lambda function"
  type        = string
  default     = "INFO"
}

# ============================================================================
# SCHEDULE CONFIGURATION
# ============================================================================

variable "schedule_name" {
  description = "EventBridge schedule name"
  type        = string
  default     = "delete-cache-daily"
}

variable "schedule_description" {
  description = "EventBridge schedule description"
  type        = string
  default     = "Delete heat map cache daily at 2 AM JST"
}

variable "schedule_expression" {
  description = "Schedule expression (cron or rate)"
  type        = string
  default     = "cron(0 2 * * ? *)" # Daily at 2 AM
}

variable "schedule_expression_timezone" {
  description = "Timezone for schedule"
  type        = string
  default     = "Asia/Tokyo"
}

variable "schedule_enabled" {
  description = "Enable the schedule"
  type        = bool
  default     = true
}

variable "schedule_input" {
  description = "Input payload for Lambda"
  type        = any
  default = {
    delete_type = "all"
    dry_run     = false
  }
}
