output "hello_world_lambda_arn" {
  description = "Hello World Lambda function ARN"
  value       = module.hello_world_lambda_dev.lambda_functions["hello-world"].function_arn
}

output "hello_world_lambda_name" {
  description = "Hello World Lambda function name"
  value       = module.hello_world_lambda_dev.lambda_functions["hello-world"].function_name
}

output "hello_world_lambda_security_group_id" {
  description = "Hello World Lambda security group ID"
  value       = module.hello_world_lambda_dev.lambda_functions["hello-world"].security_group_id
}
