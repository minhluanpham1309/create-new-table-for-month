resource "aws_iam_role" "step_functions" {
  count = var.execution_role_arn == null ? 1 : 0
  name = "${var.project_name}-${var.name}-sfn-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "states.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = merge(
    var.tags,
    {
      Name = "${var.project_name}-${var.name}-sfn-role"
    }
  )
}

locals {
  role_arn  = var.execution_role_arn != null ? var.execution_role_arn : aws_iam_role.step_functions[0].arn
  role_name = var.execution_role_arn != null ? regex("arn:aws:iam::\\d+:role/(.+)", var.execution_role_arn)[0] : aws_iam_role.step_functions[0].name
}

# Custom policy
resource "aws_iam_role_policy" "custom" {
  count = var.custom_policy_json != null ? 1 : 0
  role  = local.role_name
  policy = var.custom_policy_json
}

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
  role_arn = local.role_arn
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
      log_destination        = "${aws_cloudwatch_log_group.step_functions[0].arn}:*"
      include_execution_data = var.log_include_execution_data
      level                  = var.log_level
    }
  }

  depends_on = [
    aws_iam_role_policy.custom,
    aws_cloudwatch_log_group.step_functions
  ]
}
