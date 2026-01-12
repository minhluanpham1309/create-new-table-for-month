# Required variables
variable "project_name" {
  description = "Project name"
  type        = string
}

variable "name" {
  description = "Name of the Step Functions state machine"
  type        = string
}

variable "definition" {
  description = "Amazon States Language definition of the state machine"
  type        = string
}

# State machine configuration
variable "state_machine_type" {
  description = "Type of state machine (STANDARD or EXPRESS)"
  type        = string
  default     = "STANDARD"

  validation {
    condition     = contains(["STANDARD", "EXPRESS"], var.state_machine_type)
    error_message = "State machine type must be either STANDARD or EXPRESS."
  }
}

# Custom IAM policy
variable "custom_policy_json" {
  description = "Custom IAM policy JSON for additional permissions"
  type        = string
  default     = null
}

# Logging configuration
variable "enable_logging" {
  description = "Whether to enable CloudWatch logging"
  type        = bool
  default     = true
}

variable "log_level" {
  description = "Log level (ALL, ERROR, FATAL, OFF)"
  type        = string
  default     = "ERROR"

  validation {
    condition     = contains(["ALL", "ERROR", "FATAL", "OFF"], var.log_level)
    error_message = "Log level must be ALL, ERROR, FATAL, or OFF."
  }
}

variable "log_include_execution_data" {
  description = "Whether to include execution data in logs"
  type        = bool
  default     = false
}

variable "log_retention_in_days" {
  description = "CloudWatch log retention in days"
  type        = number
  default     = 7
}

# Tags
variable "tags" {
  description = "Additional tags"
  type        = map(string)
  default     = {}
}

variable "execution_role_arn" {
  description = "ARN of the IAM role for Step Function execution. If set, module will use this role."
  type        = string
  default     = null
}

variable "logging_role_arn" {
  description = "ARN of the IAM role for Step Function logging. If set, module will use this role."
  type        = string
  default     = null
}

variable "sns_topic_arn" {
  description = "ARN of the SNS topic to notify. If set, module will use this topic."
  type        = string
  default     = null
}
