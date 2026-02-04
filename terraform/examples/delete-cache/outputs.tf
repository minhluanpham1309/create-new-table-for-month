# ============================================================================
# DELETE CACHE EXAMPLE - OUTPUTS
# ============================================================================

output "lambda_function_name" {
  description = "Name of the Lambda function"
  value       = module.delete_cache.lambda_function_name
}

output "lambda_function_arn" {
  description = "ARN of the Lambda function"
  value       = module.delete_cache.lambda_function_arn
}

output "lambda_log_group_name" {
  description = "CloudWatch log group name for Lambda"
  value       = module.delete_cache.lambda_log_group_name
}

output "schedule_name" {
  description = "Name of the EventBridge schedule"
  value       = module.delete_cache.schedule_name
}

output "schedule_arn" {
  description = "ARN of the EventBridge schedule"
  value       = module.delete_cache.schedule_arn
}

output "lambda_role_arn" {
  description = "ARN of the Lambda IAM role"
  value       = aws_iam_role.lambda_delete_cache.arn
}

output "scheduler_role_arn" {
  description = "ARN of the EventBridge Scheduler IAM role"
  value       = aws_iam_role.scheduler.arn
}
