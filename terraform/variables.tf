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

variable "vpc_id" {
  description = "Existing VPC ID"
  type        = string
}

variable "subnet_ids" {
  description = "Existing subnet IDs for Valkey"
  type        = list(string)
}

variable "allowed_security_group_ids" {
  description = "Security group IDs of EC2 instances allowed to access Valkey"
  type        = list(string)
  default     = []
}

variable "tags" {
  description = "Additional tags"
  type        = map(string)
  default     = {}
}

# Valkey variables
variable "enable_valkey" {
  description = "Whether to create and manage Valkey resources with Terraform"
  type        = bool
  default     = false
}

variable "valkey_node_type" {
  description = "The instance class for Valkey nodes"
  type        = string
  default     = "cache.t3.micro"
}

variable "valkey_num_cache_nodes" {
  description = "Number of cache nodes"
  type        = number
  default     = 2
}

variable "valkey_engine_version" {
  description = "Valkey engine version"
  type        = string
  default     = "8.1"
}

variable "valkey_multi_az_enabled" {
  description = "Specifies whether to enable Multi-AZ Support"
  type        = bool
  default     = true
}

variable "valkey_at_rest_encryption_enabled" {
  description = "Whether to enable encryption at rest"
  type        = bool
  default     = true
}

variable "valkey_transit_encryption_enabled" {
  description = "Whether to enable encryption in transit"
  type        = bool
  default     = true
}

variable "valkey_snapshot_retention_limit" {
  description = "Number of days to retain snapshots"
  type        = number
  default     = 7
}

variable "valkey_snapshot_window" {
  description = "Time window for snapshots"
  type        = string
  default     = "03:00-04:00"
}

variable "valkey_maintenance_window" {
  description = "Maintenance window"
  type        = string
  default     = "sun:04:00-sun:05:00"
}

variable "valkey_alarm_actions" {
  description = "List of SNS topic ARNs for CloudWatch alarms"
  type        = list(string)
  default     = []
}

variable "valkey_enable_cloudwatch_alarms" {
  description = "Whether to create CloudWatch alarms"
  type        = bool
  default     = true
}

variable "valkey_memory_alarm_threshold" {
    description = "Memory usage alarm threshold in bytes"
    type        = number
    default     = 524288000 # 500 MB
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
  description = "Configuration for monthly-adding-site-tables-producer"
  type = object({
    # Lambda
    lambda_function_name         = string
    lambda_handler               = optional(string, "lambda_function.lambda_handler")
    lambda_runtime               = optional(string, "python3.11")
    lambda_timeout               = optional(number, 900)
    lambda_memory_size           = optional(number, 256)
    lambda_architectures         = optional(list(string), ["x86_64"])
    lambda_environment_variables = optional(map(string), {})
    lambda_log_retention_in_days = optional(number, 7)

    # Lambda IAM Role (Auto-create if null)
    lambda_inline_policies = optional(map(string), {})

    # VPC Configuration
    vpc_config = optional(object({
      vpc_id             = string
      subnet_ids         = list(string)
      security_group_ids = list(string)
    }))
    create_security_group = optional(bool, false)
    rds_security_group_id = optional(string, null)
    smg_end_point_sg_id   = optional(string, null)

    # EventBridge Scheduler
    schedule_name                = string
    schedule_description         = optional(string, "Trigger monthly-adding-site-tables-producer on a schedule")
    schedule_expression          = optional(string, "cron(0 9 * * ? *)")
    schedule_expression_timezone = optional(string, "Asia/Tokyo")
    schedule_enabled             = optional(bool, true)
    schedule_input               = optional(any, {})
    lambda_alias                 = optional(string, null)

    # Scheduler IAM Role (Auto-create if null)
    scheduler_inline_policies = optional(map(string), {})

    schedule_retry_policy = object({
      maximum_event_age_in_seconds = number
      maximum_retry_attempts       = number
    })

    # Tags
    tags = optional(map(string), {})
  })

  nullable = true
  default  = null
}

# Monthly Adding Site Tables Producer (Lambda)
variable "monthly_adding_site_tables_consumer" {
  description = "Configuration for monthly-adding-site-tables-consumer"
  type = object({
    # Lambda
    lambda_function_name         = string
    lambda_handler               = optional(string, "lambda_function.lambda_handler")
    lambda_runtime               = optional(string, "python3.11")
    lambda_timeout               = optional(number, 900)
    lambda_memory_size           = optional(number, 256)
    lambda_architectures         = optional(list(string), ["x86_64"])
    lambda_environment_variables = optional(map(string), {})
    lambda_log_retention_in_days = optional(number, 7)

    # Lambda IAM Role (Auto-create if null)
    lambda_inline_policies = optional(map(string), {})

    # VPC Configuration
    vpc_config = optional(object({
      vpc_id             = string
      subnet_ids         = list(string)
      security_group_ids = list(string)
    }))
    create_security_group = optional(bool, false)
    rds_security_group_id = optional(string, null)
    smg_end_point_sg_id   = optional(string, null)

    # Step Function Configuration
    step_function_name            = optional(string, "")
    step_function_inline_policies = optional(map(string), {})

    # SNS Configuration
    sns_topic_name          = string
    sns_display_name        = string
    sns_subscription_emails = list(string)

    # Scheduler
    schedule_name                = string
    schedule_description         = optional(string, "Trigger monthly-adding-site-tables-consumer on a schedule")
    schedule_expression          = string
    schedule_expression_timezone = optional(string, "Asia/Tokyo")
    schedule_enabled             = optional(bool, true)
    schedule_input               = optional(any, {})
    scheduler_inline_policies    = optional(map(string), {})
    schedule_retry_policy = object({
      maximum_event_age_in_seconds = number
      maximum_retry_attempts       = number
    })

    # Tags
    tags = optional(map(string), {})
  })

  nullable = true
  default  = null
}

# Delete heat map cache (Lambda + EventBridge Scheduler)
variable "delete_heat_map_cache" {
  description = "Configuration for delete_heat_map_cache"
  type = object({
    # Lambda
    lambda_function_name         = string
    lambda_handler               = optional(string, "lambda_function.lambda_handler")
    lambda_runtime               = optional(string, "python3.11")
    lambda_timeout               = optional(number, 900)
    lambda_memory_size           = optional(number, 256)
    lambda_architectures         = optional(list(string), ["x86_64"])
    lambda_environment_variables = optional(map(string), {})
    lambda_log_retention_in_days = optional(number, 7)
    lambda_alias                 = optional(string, null)

    # Lambda IAM Role (Auto-create if null)
    lambda_inline_policies = optional(map(string), {})

    # VPC Configuration
    vpc_config = optional(object({
      vpc_id             = string
      subnet_ids         = list(string)
      security_group_ids = list(string)
    }))
    create_security_group = optional(bool, false)
    rds_security_group_id = optional(string, null)
    smg_end_point_sg_id   = optional(string, null)

    # EventBridge Scheduler
    schedule_name                = string
    schedule_description         = optional(string, "Trigger delete_heat_map_cache on a schedule")
    schedule_expression          = optional(string, "cron(0 0 1 * ? *)")
    schedule_expression_timezone = optional(string, "Asia/Tokyo")
    schedule_enabled             = optional(bool, true)
    schedule_input               = optional(any, {})

    # Scheduler IAM Role (Auto-create if null)
    scheduler_inline_policies = optional(map(string), {})

    schedule_retry_policy = object({
      maximum_event_age_in_seconds = number
      maximum_retry_attempts       = number
    })

    # Tags
    tags = optional(map(string), {})
  })

  nullable = true
  default  = null
}

# Delete old data heat map (Lambda + EventBridge Scheduler)
variable "delete_old_data_heat_map" {
  description = "Configuration for delete_old_data_heat_map"
  type = object({
    # Lambda
    lambda_function_name         = string
    lambda_handler               = optional(string, "lambda_function.lambda_handler")
    lambda_runtime               = optional(string, "python3.11")
    lambda_timeout               = optional(number, 900)
    lambda_memory_size           = optional(number, 256)
    lambda_architectures         = optional(list(string), ["x86_64"])
    lambda_environment_variables = optional(map(string), {})
    lambda_log_retention_in_days = optional(number, 7)
    lambda_alias                 = optional(string, null)

    # Lambda IAM Role (Auto-create if null)
    lambda_inline_policies = optional(map(string), {})

    # VPC Configuration
    vpc_config = optional(object({
      vpc_id             = string
      subnet_ids         = list(string)
      security_group_ids = list(string)
    }))
    create_security_group = optional(bool, false)
    rds_security_group_id = optional(string, null)
    smg_end_point_sg_id   = optional(string, null)

    # EventBridge Scheduler
    schedule_name                = string
    schedule_description         = optional(string, "Trigger delete_old_data_heat_map on a schedule")
    schedule_expression          = optional(string, "cron(0 0 1 * ? *)")
    schedule_expression_timezone = optional(string, "Asia/Tokyo")
    schedule_enabled             = optional(bool, true)
    schedule_input               = optional(any, {})

    # Scheduler IAM Role (Auto-create if null)
    scheduler_inline_policies = optional(map(string), {})

    schedule_retry_policy = object({
      maximum_event_age_in_seconds = number
      maximum_retry_attempts       = number
    })

    # Tags
    tags = optional(map(string), {})
  })

  nullable = true
  default  = null
}

# Move Data to MySQL (Lambda + EventBridge Scheduler) - Connects to RDS and Valkey
variable "move_data_to_mysql" {
  description = "Configuration for move-data-to-mysql Lambda function"
  type = object({
    # Lambda
    lambda_function_name         = string
    lambda_handler               = optional(string, "lambda_function.lambda_handler")
    lambda_runtime               = optional(string, "python3.11")
    lambda_timeout               = optional(number, 300)
    lambda_memory_size           = optional(number, 512)
    lambda_architectures         = optional(list(string), ["x86_64"])
    lambda_environment_variables = optional(map(string), {})
    lambda_log_retention_in_days = optional(number, 90)
    lambda_alias                 = optional(string, null)

    # Lambda IAM Role (Auto-create if null)
    lambda_inline_policies = optional(map(string), {})

    # VPC Configuration
    vpc_config = optional(object({
      vpc_id             = string
      subnet_ids         = list(string)
      security_group_ids = list(string)
    }))
    create_security_group    = optional(bool, false)
    rds_security_group_id    = optional(string, null)
    smg_end_point_sg_id      = optional(string, null)
    valkey_security_group_id = optional(string, null)
    valkey_port              = optional(number, 6379)

    # EventBridge Scheduler (optional)
    schedule_name                = optional(string, null)
    schedule_description         = optional(string, "Trigger move-data-to-mysql on a schedule")
    schedule_expression          = optional(string, "cron(0 2 * * ? *)")
    schedule_expression_timezone = optional(string, "Asia/Tokyo")
    schedule_enabled             = optional(bool, true)
    schedule_input               = optional(any, null)

    # Scheduler IAM Role (Auto-create if null)
    scheduler_inline_policies = optional(map(string), {})

    schedule_retry_policy = optional(object({
      maximum_event_age_in_seconds = number
      maximum_retry_attempts       = number
    }), {
      maximum_event_age_in_seconds = 900
      maximum_retry_attempts       = 3
    })

    # Tags
    tags = optional(map(string), {})
  })

  nullable = true
  default  = null
}
