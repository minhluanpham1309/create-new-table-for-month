variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "ap-northeast-1"
}

variable "project_name" {
  description = "Project name"
  type        = string
  default     = "example"
}

variable "environment" {
  description = "Environment name"
  type        = string
  default     = "dev"
}

variable "s3_bucket_name" {
  description = "S3 bucket name for lambda processor"
  type        = string
  default     = "my-example-bucket"
}

variable "step_function_role_arn" {
  description = "ARN of the IAM role for Step Function execution."
  type        = string
  default     = null
}

variable "sns_topic_arn" {
  description = "ARN of the SNS topic to notify."
  type        = string
  default     = null
}

variable "eventbridge_invoke_sfn_role_arn" {
  description = "ARN of IAM role for EventBridge to invoke Step Function (must allow states:StartExecution)"
  type        = string
}
