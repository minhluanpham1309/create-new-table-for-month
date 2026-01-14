output "lambda_function_name" {
  description = "Lambda function name"
  value       = module.lambda.function_name
}

output "lambda_function_arn" {
  description = "Lambda function ARN"
  value       = module.lambda.function_arn
}

output "lambda_role_arn" {
  description = "Lambda execution role ARN (created or provided)"
  value       = local.lambda_role_arn
}

output "scheduler_role_arn" {
  description = "EventBridge Scheduler role ARN (created or provided)"
  value       = local.scheduler_role_arn
}
