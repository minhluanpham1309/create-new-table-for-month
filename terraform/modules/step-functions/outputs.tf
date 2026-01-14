output "state_machine_name" {
  description = "Name of the Step Functions state machine"
  value       = aws_sfn_state_machine.this.name
}

output "state_machine_arn" {
  description = "ARN of the Step Functions state machine"
  value       = aws_sfn_state_machine.this.arn
}

output "state_machine_id" {
  description = "ID of the Step Functions state machine"
  value       = aws_sfn_state_machine.this.id
}

output "state_machine_creation_date" {
  description = "Creation date of the state machine"
  value       = aws_sfn_state_machine.this.creation_date
}

output "state_machine_status" {
  description = "Status of the state machine"
  value       = aws_sfn_state_machine.this.status
}

output "role_arn" {
  description = "ARN of the IAM role for Step Functions"
  value       = var.execution_role_arn != null
}

output "role_name" {
  description = "Name of the IAM role for Step Functions"
  value       = var.execution_role_arn != null
}

output "log_group_name" {
  description = "CloudWatch log group name (if logging enabled)"
  value       = var.enable_logging ? aws_cloudwatch_log_group.step_functions[0].name : null
}
