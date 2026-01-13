# output "valkey_endpoint" {
#   description = "Valkey cluster endpoint"
#   value       = module.valkey.endpoint
# }
# 
# output "valkey_port" {
#   description = "Valkey port"  
#   value       = module.valkey.port
# }
# Lambda outputs
output "lambda_functions" {
  description = "Lambda functions information"
  value = {
    for name, lambda in module.lambda_functions : name => {
      function_name     = lambda.function_name
      function_arn      = lambda.function_arn
      role_arn          = lambda.role_arn
      security_group_id = lambda.security_group_id
    }
  }
}

# Step Function outputs (map)
output "step_functions" {
  description = "Step Function state machine information (map)"
  value = {
    for name, sfn in module.step_function : name => {
      state_machine_name         = sfn.state_machine_name
      state_machine_arn          = sfn.state_machine_arn
      state_machine_id           = sfn.state_machine_id
      state_machine_creation_date = sfn.state_machine_creation_date
      state_machine_status       = sfn.state_machine_status
      role_arn                   = sfn.role_arn
      role_name                  = sfn.role_name
      log_group_name             = sfn.log_group_name
    }
  }
}



# Monthly Adding Site Tables Producer outputs
# output "monthly_adding_site_tables_producers" {
#   description = "Monthly adding site tables producer info (Lambda + Scheduler)"
#   value = {
#     for k, v in module.monthly_adding_site_tables_producer : k => {
#       lambda_function_name = v.lambda_function_name
#       lambda_function_arn  = v.lambda_function_arn
#       schedule_arn         = v.schedule_arn
#       schedule_id          = v.schedule_id
#     }
#   }
# }
