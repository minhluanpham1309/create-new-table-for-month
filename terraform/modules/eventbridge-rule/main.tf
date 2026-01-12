# ============================================================================
# EVENTBRIDGE MODULE - UNIFIED PERMISSION INTERFACE
# ============================================================================
# Supports both Lambda and Step Functions with consistent permission handling
# User only needs to provide ARN - module handles permission/role automatically

# Scheduler support (EventBridge Scheduler)
resource "aws_scheduler_schedule" "this" {
  count = var.enable_scheduler ? 1 : 0
  name        = var.rule_name != null ? var.rule_name : "${var.project_name}-${var.name}"
  description = var.description
  flexible_time_window {
    mode = "OFF"
  }
  schedule_expression = var.schedule_expression
  time_zone           = var.time_zone
  state               = var.enabled ? "ENABLED" : "DISABLED"
  target {
    arn      = values(var.targets)[0].arn
    role_arn = var.scheduler_role_arn
    input    = jsonencode(lookup(values(var.targets)[0], "input", {}))
    retry_policy {
      maximum_event_age_in_seconds = try(var.scheduler_retry_policy.maximum_event_age_in_seconds, null)
      maximum_retry_attempts       = try(var.scheduler_retry_policy.maximum_retry_attempts, null)
    }
  }
  tags = merge(
    var.tags,
    {
      Name = var.rule_name != null ? var.rule_name : "${var.project_name}-${var.name}"
    }
  )
}
