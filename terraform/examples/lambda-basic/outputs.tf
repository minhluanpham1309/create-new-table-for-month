output "hello_world_lambda_arn" {
  description = "Hello World Lambda function ARN"
  value       = module.HeatmapLambdaSplitSites.lambda_functions["HeatmapLambdaSplitSites"].function_arn
}

output "hello_world_lambda_name" {
  description = "Hello World Lambda function name"
  value       = module.HeatmapLambdaSplitSites.lambda_functions["HeatmapLambdaSplitSites"].function_name
}

output "hello_world_lambda_security_group_id" {
  description = "Hello World Lambda security group ID"
  value       = module.HeatmapLambdaSplitSites.lambda_functions["HeatmapLambdaSplitSites"].security_group_id
}
