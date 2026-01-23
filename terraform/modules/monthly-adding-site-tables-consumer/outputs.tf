output "lambda_function_name" {
  description = "Lambda function name"
  value       = module.lambda.function_name
}

output "lambda_function_arn" {
  description = "Lambda function ARN"
  value       = module.lambda.function_arn
}

output "step_function_state_machine_name" {
  description = "Name of the Step Functions state machine"
  value       = module.step_function.state_machine_name
}

output "step_function_state_machine_arn" {
  description = "ARN of the Step Functions state machine"
  value       = module.step_function.state_machine_arn
}

output "sns_topic_arn" {
  description = "ARN of the SNS topic (if created)"
  value       = module.sns_topic.topic_arn
}
