terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.29.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# Basic Lambda function - Gọi trực tiếp module lambda-function
module "hello_world_lambda" {
  source = "../../modules/lambda-function"

  project_name  = var.project_name
  function_name = "hello-world"
  handler       = "lambda_function.handler"
  runtime       = "python3.11"

  timeout     = 30
  memory_size = 256

  environment_variables = {
    ENVIRONMENT = var.environment
    LOG_LEVEL   = "INFO"
  }

  log_retention_in_days = 7

  tags = {
    Environment = var.environment
    ManagedBy   = "Terraform"
  }

  role_arn = "arn:aws:iam::683918607581:role/excute-lambda"

  create_security_group = true
  vpc_config = {
    vpc_id             = "vpc-08586cd9f6ce3a905"
    subnet_ids         = ["subnet-0ffa21d23c30bbf14", "subnet-09e78cbbf83798d9a", "subnet-0071f6115ba604b19"]
    security_group_ids = []
  }

  security_group_egress_rules = [{
    from_port   = 3306
    to_port     = 3306
    protocol    = "tcp"
    cidr_blocks = ["10.0.1.0/24"]
    description = "Allow Lambda to access RDS MySQL"
  }]

  rds_security_group_ids = ["sg-0ec24edb38ce58304"]
}

data "aws_security_group" "rds" {
  filter {
    name   = "group-id"
    values = ["sg-0ec24edb38ce58304"]
  }
}

resource "aws_vpc_security_group_ingress_rule" "lambda_to_rds" {
  security_group_id            = data.aws_security_group.rds.id
  from_port                   = 3306
  to_port                     = 3306
  ip_protocol                 = "tcp"
  referenced_security_group_id = module.hello_world_lambda.security_group_id

  depends_on = [module.hello_world_lambda]
}

