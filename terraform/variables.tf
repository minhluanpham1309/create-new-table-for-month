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

# Commented out - Valkey configuration variables
# variable "valkey_node_type" {
#   description = "The instance class for Valkey nodes"
#   type        = string
#   default     = "cache.t3.micro"
# }
# 
# variable "valkey_num_cache_nodes" {
#   description = "Number of cache nodes"
#   type        = number
#   default     = 2
# }
# 
# variable "valkey_engine_version" {
#   description = "Valkey engine version"
#   type        = string
#   default     = "8.1"
# }
# 
# variable "valkey_multi_az_enabled" {
#   description = "Specifies whether to enable Multi-AZ Support"
#   type        = bool
#   default     = true
# }
# 
# variable "valkey_at_rest_encryption_enabled" {
#   description = "Whether to enable encryption at rest"
#   type        = bool
#   default     = true
# }
# 
# variable "valkey_transit_encryption_enabled" {
#   description = "Whether to enable encryption in transit"
#   type        = bool
#   default     = true
# }
# 
# variable "valkey_snapshot_retention_limit" {
#   description = "Number of days to retain snapshots"
#   type        = number
#   default     = 7
# }
# 
# variable "valkey_snapshot_window" {
#   description = "Time window for snapshots"
#   type        = string
#   default     = "03:00-04:00"
# }
# 
# variable "valkey_maintenance_window" {
#   description = "Maintenance window"
#   type        = string
#   default     = "sun:04:00-sun:05:00"
# }
# 
# variable "valkey_enable_cloudwatch_alarms" {
#   description = "Whether to create CloudWatch alarms"
#   type        = bool
#   default     = true
# }

# Lambda variables
variable "lambda_functions" {
  description = "Map of Lambda functions to create"
  type = map(object({
    function_name         = string
    handler              = string
    runtime              = string
    timeout              = optional(number, 30)
    memory_size          = optional(number, 256)
    environment_variables = optional(map(string))
    role_arn             = string
    create_security_group = optional(bool, false)
    vpc_config           = optional(object({
      vpc_id             = string
      subnet_ids         = list(string)
      security_group_ids = list(string)
    }))
    enable_cloudwatch_alarms = optional(bool, false)
    rds_security_group_ids = optional(list(string), [])
  }))
  default = {}
}

# Step Function variables (unified object map)
variable "step_functions" {
  description = "Map of Step Functions to create"
  type = map(object({
    name         = string
    definition   = string
    lambda_arns  = list(string)
    tags         = optional(map(string))
    state_machine_type = optional(string, "STANDARD")
    custom_policy_json = optional(string)
    enable_logging     = optional(bool, true)
    log_level                = optional(string, "OFF")
    log_include_execution_data = optional(bool, false)
    log_retention_in_days      = optional(number, 7)
  }))
  default = {}
}

variable "eventbridge_rules" {
  type = map(object({
    name                = string
    description         = optional(string)
    schedule_expression = string
    enabled             = optional(bool, true)
    time_zone           = optional(string)
    scheduler_retry_policy = optional(object({
      maximum_event_age_in_seconds = optional(number)
      maximum_retry_attempts       = optional(number)
    }))
    targets = map(object({
      type  = string  # "lambda" | "step_functions" | "sns"
      arn   = string
      input = optional(any)
    }))
    tags = optional(map(string))
  }))
  default = {}
}

variable "rds_security_group_ids" {
  description = "List of RDS security group IDs for Lambda ingress rules"
  type        = list(string)
  default     = []
}
