# Step Functions State Machine
resource "aws_sfn_state_machine" "this" {
  name     = var.state_name
  role_arn = var.role_arn

  definition = var.definition

  tags = merge(
    var.tags,
    {
      Name = var.state_name
    }
  )

  lifecycle {
    ignore_changes = [definition]
  }
}