output "scheduler_arn" {
  description = "ARN of the EventBridge Scheduler schedule (if enabled)"
  value       = var.enable_scheduler ? aws_scheduler_schedule.this[0].arn : null
}

output "scheduler_id" {
  description = "ID of the EventBridge Scheduler schedule (if enabled)"
  value       = var.enable_scheduler ? aws_scheduler_schedule.this[0].id : null
}

