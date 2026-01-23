# Required variables for the lambda-function module
variable "project_name" {
  description = "Project name"
  type        = string
}

variable "function_name" {
  description = "Name of the Lambda function (will be prefixed with project_name)"
  type        = string
}

variable "handler" {
  description = "Lambda function handler"
  type        = string
}

variable "runtime" {
  description = "Lambda runtime"
  type        = string
}

# Deployment package configuration (one of these must be provided)
variable "filename" {
  description = "Path to the function's deployment package within the local filesystem"
  type        = string
  default     = null
}

variable "source_code_hash" {
  description = "Used to trigger updates. Must be set to a base64-encoded SHA256 hash of the package file"
  type        = string
  default     = null
}

# Function configuration
variable "timeout" {
  description = "Function timeout in seconds"
  type        = number
}

variable "memory_size" {
  description = "Amount of memory in MB your Lambda Function can use at runtime"
  type        = number
}

variable "architectures" {
  description = "Instruction set architecture for your Lambda function"
  type        = list(string)
}

variable "environment_variables" {
  description = "Map of environment variables for the Lambda function"
  type        = map(string)
}

# VPC configuration
variable "vpc_config" {
  description = "VPC configuration for Lambda function"
  type = object({
    vpc_id             = string
    subnet_ids         = list(string)
    security_group_ids = list(string)
  })
}

variable "create_security_group" {
  description = "Whether to create a security group for Lambda function"
  type        = bool
}

variable "log_retention_in_days" {
  description = "CloudWatch log retention in days"
  type        = number
}

variable "tags" {
  description = "Additional tags to apply to all resources in this module"
  type        = map(string)
}

variable "role_arn" {
  description = "IAM role ARN to use for Lambda function. If not set, a new role will be created."
  type        = string
}

variable "rds_security_group_id" {
  description = "RDS Security Group ID to allow Lambda access to RDS instance (if applicable)"
  type        = string
}

variable "smg_end_point_sg_id" {
  description = "Secret Manager Security Group ID to allow Lambda access to Secret Manager (if applicable)"
  type        = string
}
