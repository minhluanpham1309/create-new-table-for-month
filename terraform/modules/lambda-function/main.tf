# CloudWatch Log Group
resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${var.function_name}"
  retention_in_days = var.log_retention_in_days

  tags = merge(
    var.tags,
    {
      Name = "${var.function_name}-logs"
    }
  )
}

# Create dummy zip file
data "archive_file" "dummy" {
  type        = "zip"
  output_path = "${path.module}/.terraform/dummy.zip"

  source {
    filename = "lambda_function.py"
    content  = "def handler(event, context):\n    return {'statusCode': 200, 'body': 'Dummy Lambda'}"
  }
}

# Security Group for Lambda (if VPC is configured)
resource "aws_security_group" "lambda" {
  count       = var.vpc_config != null && var.create_security_group ? 1 : 0
  name_prefix = "${var.function_name}-"
  vpc_id      = var.vpc_config.vpc_id
  description = "Security group for Lambda function ${var.function_name}"
  
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Allow all outbound traffic"
  }

  tags = merge(
    var.tags,
    {
      Name = "${var.project_name}-${var.function_name}-sg"
    }
  )

  lifecycle {
    create_before_destroy = true
  }
}

# Ingress rule on RDS security group to allow Lambda access
resource "aws_vpc_security_group_ingress_rule" "rds_from_lambda" {
  count                        = var.create_security_group && var.rds_security_group_id != null ? 1 : 0
  security_group_id            = var.rds_security_group_id
  from_port                    = 3306
  to_port                      = 3306
  ip_protocol                  = "tcp"
  description                  = "Allow Lambda ${var.function_name} to access RDS"
  referenced_security_group_id = aws_security_group.lambda[0].id

  depends_on = [aws_security_group.lambda]
}

resource "aws_vpc_security_group_ingress_rule" "smg_from_lambda" {
  count                        = var.create_security_group && var.smg_end_point_sg_id != null ? 1 : 0
  security_group_id            = var.smg_end_point_sg_id
  from_port                    = 443
  to_port                      = 443
  ip_protocol                  = "tcp"
  description                  = "Allow Lambda ${var.function_name} to access Secrets Manager"
  referenced_security_group_id = aws_security_group.lambda[0].id

  depends_on = [aws_security_group.lambda]
}

# Lambda Function
resource "aws_lambda_function" "this" {
  function_name = var.function_name
  role          = var.role_arn
  handler       = var.handler
  runtime       = var.runtime
  timeout       = var.timeout
  memory_size   = var.memory_size
  architectures = var.architectures

  dynamic "environment" {
    for_each = var.environment_variables != null ? [1] : []
    content {
      variables = var.environment_variables
    }
  }

  dynamic "vpc_config" {
    for_each = var.vpc_config != null ? [var.vpc_config] : []
    content {
      subnet_ids = vpc_config.value["subnet_ids"]
      security_group_ids = concat(
        var.create_security_group ? [aws_security_group.lambda[0].id] : [],
        vpc_config.value["security_group_ids"]
      )
    }
  }

  filename         = coalesce(var.filename, data.archive_file.dummy.output_path)
  source_code_hash = coalesce(var.source_code_hash, data.archive_file.dummy.output_base64sha256)

  lifecycle {
    ignore_changes = [filename, source_code_hash] # Ignore changes to avoid unnecessary updates
    
    precondition {
      condition     = var.vpc_config == null || var.create_security_group || length(try(var.vpc_config.security_group_ids, [])) > 0
      error_message = "When vpc_config is specified, either create_security_group must be true or vpc_config.security_group_ids must contain at least one security group ID."
    }
  }

  tags = merge(
    var.tags,
    {
      Name = "${var.project_name}-${var.function_name}"
    }
  )

  depends_on = [
    aws_cloudwatch_log_group.lambda,
    aws_security_group.lambda
  ]
}
