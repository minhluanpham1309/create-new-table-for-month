# CloudWatch Log Group for Step Functions
resource "aws_cloudwatch_log_group" "step_functions" {
  count             = var.enable_logging ? 1 : 0
  name              = "/aws/vendedlogs/states/${var.project_name}-${var.name}"
  retention_in_days = var.log_retention_in_days

  tags = merge(
    var.tags,
    {
      Name = "${var.project_name}-${var.name}-logs"
    }
  )
}

# Step Functions State Machine
resource "aws_sfn_state_machine" "this" {
  name     = "${var.project_name}-${var.name}"
  role_arn = var.execution_role_arn
  type     = var.state_machine_type

  definition = var.definition

  tags = merge(
    var.tags,
    {
      Name = "${var.project_name}-${var.name}"
    }
  )

  dynamic "logging_configuration" {
    for_each = var.enable_logging ? [1] : []
    content {
      log_destination = "${aws_cloudwatch_log_group.step_functions[0].arn}:*"
      level           = var.log_level
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.step_functions
  ]
}