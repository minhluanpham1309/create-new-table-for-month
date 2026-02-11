# ============================================================================
# EVENTBRIDGE MODULE - UNIFIED PERMISSION INTERFACE
# ============================================================================
# Supports both Lambda and Step Functions with consistent permission handling
# User only needs to provide ARN - module handles permission/role automatically

# Scheduler support (EventBridge Scheduler)
resource "aws_scheduler_schedule" "this" {
  name        = var.name
  description = var.description

  flexible_time_window {
    mode = "OFF"
  }

  schedule_expression          = var.schedule_expression
  schedule_expression_timezone = var.schedule_expression_timezone
  state                        = var.enabled ? "ENABLED" : "DISABLED"

  target {
    arn      = "${var.target.arn}:${var.target.alias}"
    role_arn = var.scheduler_role_arn
    input    = var.target.input != null ? jsonencode(var.target.input) : null

    dynamic "retry_policy" {
      for_each = var.retry_policy != null ? [1] : []
      content {
        maximum_retry_attempts       = var.retry_policy.maximum_retry_attempts
        maximum_event_age_in_seconds = var.retry_policy.maximum_event_age_in_seconds
      }
    }
  }
}
