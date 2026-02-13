output "function_name" {
  description = "Lambda function name"
  value       = aws_lambda_function.this.function_name
}

output "function_arn" {
  description = "Lambda function ARN"
  value       = aws_lambda_function.this.arn
}

output "security_group_id" {
  description = "Security group ID of the Lambda function"
  value       = var.create_security_group && length(aws_security_group.lambda) > 0 ? aws_security_group.lambda[0].id : null
}
