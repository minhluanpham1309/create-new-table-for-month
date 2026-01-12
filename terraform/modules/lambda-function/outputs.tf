output "function_name" {
  description = "Lambda function name"
  value       = aws_lambda_function.this.function_name
}

output "function_arn" {
  description = "Lambda function ARN"
  value       = aws_lambda_function.this.arn
}

output "function_version" {
  description = "Latest published version of Lambda function"
  value       = aws_lambda_function.this.version
}

output "function_last_modified" {
  description = "Date Lambda function was last modified"
  value       = aws_lambda_function.this.last_modified
}

output "role_arn" {
  description = "IAM role ARN used by Lambda function"
  value       = var.role_arn
}

output "role_name" {
  description = "IAM role name used by Lambda function"
  value       = var.role_arn
}

output "log_group_name" {
  description = "CloudWatch log group name"
  value       = aws_cloudwatch_log_group.lambda.name
}

output "log_group_arn" {
  description = "CloudWatch log group ARN"
  value       = aws_cloudwatch_log_group.lambda.arn
}

output "security_group_id" {
  description = "Security group ID (if created)"
  value       = var.create_security_group && var.vpc_config != null ? try(aws_security_group.lambda[0].id, null) : null
}