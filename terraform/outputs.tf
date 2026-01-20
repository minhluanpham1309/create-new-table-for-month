output "valkey_endpoint" {
  description = "Valkey cluster endpoint"
  value       = module.valkey.endpoint
}

output "valkey_port" {
  description = "Valkey port"
  value       = module.valkey.port
}

# Monthly Adding Site Tables Producer outputs
output "monthly_adding_site_tables_producer" {
  description = "Monthly adding site tables producer info (Lambda + Scheduler). Null if disabled."
  value = try({
    lambda_function_name = module.monthly_adding_site_tables_producer[0].lambda_function_name
    lambda_function_arn  = module.monthly_adding_site_tables_producer[0].lambda_function_arn
  }, null)
}
