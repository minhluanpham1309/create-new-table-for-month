variable "project_name" {
  description = "Project name used as prefix for resources"
  type        = string
}

variable "tags" {
  description = "Additional tags"
  type        = map(string)
  default     = {}
}

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
  default     = 900
}

variable "lambda_memory_size" {
  description = "Lambda memory size (MB)"
  type        = number
  default     = 256
}

variable "lambda_architectures" {
  description = "Lambda architectures"
  type        = list(string)
  default     = ["x86_64"]
}

variable "lambda_environment_variables" {
  description = "Additional env vars for lambda (ENVIRONMENT is added automatically)"
  type        = map(string)
  default     = {}
}

variable "lambda_role_arn" {
  description = "IAM role ARN for lambda. If null, module will auto-create with policies from lambda_inline_policies"
  type        = string
  default     = null
}

variable "lambda_inline_policies" {
  description = "Map of inline policy names to policy documents (JSON string) for Lambda role. Only used when lambda_role_arn is null"
  type        = map(string)
  default     = {}
}

variable "lambda_log_retention_in_days" {
  description = "CloudWatch log retention for lambda"
  type        = number
  default     = 7
}

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

variable "schedule_name" {
  description = "Logical schedule name (will be prefixed by project_name unless rule_name is provided)"
  type        = string
}

variable "schedule_description" {
  description = "Schedule description"
  type        = string
  default     = null
}

variable "schedule_expression" {
  description = "Schedule expression"
  type        = string
  default     = "cron(0 9 * * ? *)"
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
  description = "Optional input payload for the target"
  type        = any
  default     = {}
}

variable "scheduler_role_arn" {
  description = "IAM role ARN for EventBridge Scheduler. If null, module will auto-create with invoke-lambda permission"
  type        = string
  default     = null
}

variable "scheduler_inline_policies" {
  description = "Additional inline policies for Scheduler role (invoke-lambda is auto-added). Only used when scheduler_role_arn is null"
  type        = map(string)
  default     = {}
}
