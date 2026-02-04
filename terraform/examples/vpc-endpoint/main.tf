# Ví dụ: Sử dụng module VPC Endpoint

# Tạo VPC Endpoint cho Secrets Manager (Interface Endpoint)
module "secrets_manager_endpoint" {
  source = "../../modules/vpc-endpoint"

  project_name      = "my-project"
  endpoint_name     = "secretsmanager"
  vpc_id            = "vpc-xxxxxxxxxxxxx"
  service_name      = "com.amazonaws.ap-northeast-1.secretsmanager"
  vpc_endpoint_type = "Interface"

  # Interface endpoint configuration
  subnet_ids             = ["subnet-xxxxx", "subnet-yyyyy"]
  security_group_ids     = ["sg-xxxxxxxxxxxxx"]  # Security group phải tạo sẵn
  private_dns_enabled    = true

  tags = {
    Environment = "dev"
    ManagedBy   = "terraform"
  }
}

# Tạo VPC Endpoint cho SQS (Interface Endpoint)
module "sqs_endpoint" {
  source = "../../modules/vpc-endpoint"

  project_name      = "my-project"
  endpoint_name     = "sqs"
  vpc_id            = "vpc-xxxxxxxxxxxxx"
  service_name      = "com.amazonaws.ap-northeast-1.sqs"
  vpc_endpoint_type = "Interface"

  # Interface endpoint configuration
  subnet_ids             = ["subnet-xxxxx", "subnet-yyyyy"]
  security_group_ids     = ["sg-xxxxxxxxxxxxx"]  # Security group phải tạo sẵn
  private_dns_enabled    = true

  tags = {
    Environment = "dev"
    ManagedBy   = "terraform"
  }
}

# Tạo VPC Endpoint cho S3 (Gateway Endpoint)
module "s3_endpoint" {
  source = "../../modules/vpc-endpoint"

  project_name      = "my-project"
  endpoint_name     = "s3"
  vpc_id            = "vpc-xxxxxxxxxxxxx"
  service_name      = "com.amazonaws.ap-northeast-1.s3"
  vpc_endpoint_type = "Gateway"

  # Gateway endpoint configuration
  route_table_ids = ["rtb-xxxxx", "rtb-yyyyy"]

  tags = {
    Environment = "dev"
    ManagedBy   = "terraform"
  }
}

# Tạo VPC Endpoint cho DynamoDB (Gateway Endpoint)
module "dynamodb_endpoint" {
  source = "../../modules/vpc-endpoint"

  project_name      = "my-project"
  endpoint_name     = "dynamodb"
  vpc_id            = "vpc-xxxxxxxxxxxxx"
  service_name      = "com.amazonaws.ap-northeast-1.dynamodb"
  vpc_endpoint_type = "Gateway"

  # Gateway endpoint configuration
  route_table_ids = ["rtb-xxxxx", "rtb-yyyyy"]

  tags = {
    Environment = "dev"
    ManagedBy   = "terraform"
  }
}

# Outputs
output "secrets_manager_endpoint_id" {
  description = "Secrets Manager VPC Endpoint ID"
  value       = module.secrets_manager_endpoint.vpc_endpoint_id
}

output "sqs_endpoint_id" {
  description = "SQS VPC Endpoint ID"
  value       = module.sqs_endpoint.vpc_endpoint_id
}


output "s3_endpoint_id" {
  description = "S3 VPC Endpoint ID"
  value       = module.s3_endpoint.vpc_endpoint_id
}

output "dynamodb_endpoint_id" {
  description = "DynamoDB VPC Endpoint ID"
  value       = module.dynamodb_endpoint.vpc_endpoint_id
}
