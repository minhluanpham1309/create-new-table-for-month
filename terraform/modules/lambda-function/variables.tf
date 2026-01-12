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
  type    = string
  default = null
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
  default     = 30
}

variable "memory_size" {
  description = "Amount of memory in MB your Lambda Function can use at runtime"
  type        = number
  default     = 256
}

variable "architectures" {
  description = "Instruction set architecture for your Lambda function"
  type        = list(string)
  default     = ["x86_64"]
}

variable "environment_variables" {
  description = "Map of environment variables for the Lambda function"
  type        = map(string)
  default     = null
}

# VPC configuration
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
  description = "Whether to create a security group for Lambda function"
  type        = bool
  default     = false
}

variable "log_retention_in_days" {
  description = "CloudWatch log retention in days"
  type        = number
  default     = 7
}

variable "tags" {
  description = "Additional tags to apply to all resources in this module"
  type        = map(string)
  default     = {}
}

variable "role_arn" {
  description = "IAM role ARN to use for Lambda function. If not set, a new role will be created.\n\nNếu truyền role_arn, role này phải có trust policy như sau:\n{\n  \"Effect\": \"Allow\",\n  \"Principal\": { \"Service\": \"lambda.amazonaws.com\" },\n  \"Action\": \"sts:AssumeRole\"\n}\nVà phải được attach policy AWSLambdaBasicExecutionRole."
  type        = string
  default     = null
}

variable "rds_security_group_ids" {
  description = "List of RDS security group IDs for Lambda ingress rules"
  type        = list(string)
  default     = []
}
