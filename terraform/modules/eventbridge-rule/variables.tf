# ============================================================================
# EVENTBRIDGE MODULE - UNIFIED VARIABLES
# ============================================================================

# Required variables
variable "project_name" {
  description = "Project name"
  type        = string
}

variable "name" {
  description = "Name of the EventBridge schedule (will be prefixed with project_name)"
  type        = string
}

# ============================================================================
# SCHEDULE CONFIGURATION
# ============================================================================

variable "rule_name" {
  description = "Full schedule name (overrides project_name-name if set)"
  type        = string
  default     = null
}

variable "description" {
  description = "Description of the schedule"
  type        = string
  default     = null
}

variable "schedule_expression" {
  description = "Schedule expression (e.g., 'rate(5 minutes)' or 'cron(0 9 * * ? *)')"
  type        = string
  default     = null
}

variable "enabled" {
  description = "Whether the schedule is enabled"
  type        = bool
  default     = true
}

variable "enable_scheduler" {
  description = "If true, use EventBridge Scheduler (aws_scheduler_schedule)"
  type        = bool
  default     = false
}

variable "time_zone" {
  description = "Time zone for EventBridge Scheduler (e.g. 'Asia/Ho_Chi_Minh'). Default is UTC."
  type        = string
  default     = "UTC"
}

variable "scheduler_retry_policy" {
  description = "Retry policy for EventBridge Scheduler. Object with maximum_event_age_in_seconds and maximum_retry_attempts."
  type = object({
    maximum_event_age_in_seconds = optional(number)
    maximum_retry_attempts       = optional(number)
  })
  default = {}
}

variable "scheduler_role_arn" {
  description = "IAM role ARN for EventBridge Scheduler (must allow scheduler.amazonaws.com and permission to invoke target)"
  type        = string
  default     = null
}

# ============================================================================
# TARGETS CONFIGURATION
# ============================================================================
# This is the KEY improvement - single interface for all target types!

variable "targets" {
  type = map(object({
    type      = string  # "lambda" | "step_functions" | "sns"
    arn       = string
    input     = optional(any)
  }))

  default = {}
}

# ============================================================================
# TAGS
# ============================================================================

variable "tags" {
  description = "Additional tags to apply to all resources"
  type        = map(string)
  default     = {}
}
