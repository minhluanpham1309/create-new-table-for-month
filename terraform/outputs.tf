output "valkey_endpoint" {
  description = "Valkey cluster endpoint"
  value       = var.enable_valkey ? module.valkey[0].endpoint : null
}

output "valkey_port" {
  description = "Valkey port"
  value       = var.enable_valkey ? module.valkey[0].port : null
}

# Monthly Adding Site Tables Producer outputs
output "monthly_adding_site_tables_producer" {
  description = "Monthly adding site tables producer info (Lambda + Scheduler). Null if disabled."
  value = try({
    lambda_function_name = module.monthly_adding_site_tables_producer[0].lambda_function_name
    lambda_function_arn  = module.monthly_adding_site_tables_producer[0].lambda_function_arn
  }, null)
}

# Monthly Adding Site Tables Consumer outputs
output "monthly_adding_site_tables_consumer" {
  description = "Monthly adding site tables consumer info (Lambda + Step Function). Null if disabled."
  value = try({
    lambda_function_name             = module.monthly_adding_site_tables_consumer[0].lambda_function_name
    lambda_function_arn              = module.monthly_adding_site_tables_consumer[0].lambda_function_arn
    step_function_state_machine_name = module.monthly_adding_site_tables_consumer[0].step_function_state_machine_name
    step_function_state_machine_arn  = module.monthly_adding_site_tables_consumer[0].step_function_state_machine_arn
    sns_topic_arn                    = module.monthly_adding_site_tables_consumer[0].sns_topic_arn
  }, null)
}
