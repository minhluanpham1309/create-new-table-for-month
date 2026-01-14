resource "aws_iam_role" "this" {
  name                  = var.role_name
  assume_role_policy    = var.assume_role_policy
  description           = var.description
  max_session_duration  = var.max_session_duration
  force_detach_policies = var.force_detach_policies
  path                  = var.path

  tags = merge(
    var.tags,
    {
      Name = var.role_name
    }
  )
}

# Attach managed policies
resource "aws_iam_role_policy_attachment" "managed" {
  for_each = toset(var.managed_policy_arns)

  role       = aws_iam_role.this.name
  policy_arn = each.value
}

# Attach inline policies from JSON
resource "aws_iam_role_policy" "inline" {
  for_each = var.inline_policies

  name   = each.key
  role   = aws_iam_role.this.id
  policy = each.value
}

