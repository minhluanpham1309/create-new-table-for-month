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

  validation {
    condition     = var.schedule_expression != null && trimspace(var.schedule_expression) != ""
    error_message = "schedule_expression must be provided and non-empty."
  }
}

variable "enabled" {
  description = "Whether the schedule is enabled"
  type        = bool
  default     = true
}

variable "schedule_expression_timezone" {
  description = "Time zone for EventBridge Scheduler (e.g. 'Asia/Ho_Chi_Minh'). Default is UTC."
  type        = string
  default     = "Asia/Tokyo"
}


variable "scheduler_role_arn" {
  description = "IAM role ARN for EventBridge Scheduler (must allow scheduler.amazonaws.com and permission to invoke target)"
  type        = string
  default     = null
}

# ============================================================================
# TARGETS CONFIGURATION
# ============================================================================
# EventBridge Scheduler supports a single target per schedule
variable "target" {
  description = "Target configuration for the EventBridge schedule"
  type = object({
    type  = string # "lambda" | "step_functions" | "sns"
    arn   = string
    input = optional(any)
  })

  default = null
}
