# ============================================================================
# EVENTBRIDGE SCHEDULER MODULE - OUTPUTS
# ============================================================================

output "schedule_name" {
  description = "Name of the EventBridge schedule"
  value       = aws_scheduler_schedule.this.name
}

output "schedule_arn" {
  description = "ARN of the EventBridge schedule"
  value       = aws_scheduler_schedule.this.arn
}

output "schedule_id" {
  description = "ID of the EventBridge schedule"
  value       = aws_scheduler_schedule.this.id
}

output "schedule_state" {
  description = "State of the EventBridge schedule (ENABLED or DISABLED)"
  value       = aws_scheduler_schedule.this.state
}
