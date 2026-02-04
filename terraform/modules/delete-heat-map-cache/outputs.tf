# ============================================================================
# DELETE HEAT MAP CACHE MODULE - OUTPUTS
# ============================================================================

output "lambda_function_name" {
  description = "Name of the Lambda function"
  value       = module.lambda.function_name
}

output "lambda_function_arn" {
  description = "ARN of the Lambda function"
  value       = module.lambda.function_arn
}

output "lambda_function_invoke_arn" {
  description = "Invoke ARN of the Lambda function"
  value       = module.lambda.function_invoke_arn
}

output "lambda_log_group_name" {
  description = "Name of the CloudWatch log group for Lambda"
  value       = module.lambda.log_group_name
}

output "schedule_name" {
  description = "Name of the EventBridge schedule"
  value       = module.schedule.schedule_name
}

output "schedule_arn" {
  description = "ARN of the EventBridge schedule"
  value       = module.schedule.schedule_arn
}
