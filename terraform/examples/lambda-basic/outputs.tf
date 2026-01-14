output "producer_lambda_arn" {
  description = "Producer Lambda function ARN"
  value       = module.heatmap_japan_dev.monthly_adding_site_tables_producer.lambda_function_arn
}

output "producer_lambda_name" {
  description = "Producer Lambda function name"
  value       = module.heatmap_japan_dev.monthly_adding_site_tables_producer.lambda_function_name
}
