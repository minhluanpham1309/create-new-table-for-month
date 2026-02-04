# ============================================================================
# DELETE CACHE EXAMPLE - BASIC USAGE
# ============================================================================
# This example demonstrates basic usage of the delete-heat-map-cache module
# without VPC configuration.
# ============================================================================

terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# ============================================================================
# DATA SOURCES
# ============================================================================

data "aws_caller_identity" "current" {}

# ============================================================================
# IAM ROLE FOR LAMBDA
# ============================================================================

resource "aws_iam_role" "lambda_delete_cache" {
  name = "${var.project_name}-delete-cache-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = var.tags
}

# Lambda basic execution policy
resource "aws_iam_role_policy_attachment" "lambda_basic" {
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
  role       = aws_iam_role.lambda_delete_cache.name
}

# Custom policy for cache deletion
resource "aws_iam_role_policy" "lambda_delete_cache_policy" {
  name = "${var.project_name}-delete-cache-policy"
  role = aws_iam_role.lambda_delete_cache.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "elasticache:DescribeCacheClusters",
          "elasticache:ModifyCacheCluster",
          "elasticache:DescribeReplicationGroups"
        ]
        Resource = "*"
      }
    ]
  })
}

# ============================================================================
# IAM ROLE FOR EVENTBRIDGE SCHEDULER
# ============================================================================

resource "aws_iam_role" "scheduler" {
  name = "${var.project_name}-delete-cache-scheduler-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "scheduler.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = var.tags
}

resource "aws_iam_role_policy" "scheduler_invoke_lambda" {
  name = "${var.project_name}-scheduler-invoke-lambda"
  role = aws_iam_role.scheduler.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "lambda:InvokeFunction"
        ]
        Resource = module.delete_cache.lambda_function_arn
      }
    ]
  })
}

# ============================================================================
# DELETE CACHE MODULE
# ============================================================================

module "delete_cache" {
  source = "../../modules/delete-heat-map-cache"

  project_name = var.project_name

  # Lambda configuration
  lambda_function_name = var.lambda_function_name
  lambda_handler       = var.lambda_handler
  lambda_runtime       = var.lambda_runtime
  lambda_timeout       = var.lambda_timeout
  lambda_memory_size   = var.lambda_memory_size
  lambda_architectures = var.lambda_architectures

  lambda_environment_variables = {
    CACHE_TYPE     = var.cache_type
    REDIS_ENDPOINT = var.redis_endpoint
    LOG_LEVEL      = var.log_level
    ENVIRONMENT    = var.environment
  }

  lambda_role_arn           = aws_iam_role.lambda_delete_cache.arn
  lambda_log_retention_in_days = var.lambda_log_retention_in_days

  # No VPC configuration in this basic example
  vpc_config            = null
  create_security_group = false

  # Schedule configuration
  schedule_name                = var.schedule_name
  schedule_description         = var.schedule_description
  schedule_expression          = var.schedule_expression
  schedule_expression_timezone = var.schedule_expression_timezone
  schedule_enabled             = var.schedule_enabled
  scheduler_role_arn           = aws_iam_role.scheduler.arn

  schedule_input = var.schedule_input

  schedule_retry_policy = {
    maximum_event_age_in_seconds = 3600
    maximum_retry_attempts       = 3
  }

  tags = var.tags
}
