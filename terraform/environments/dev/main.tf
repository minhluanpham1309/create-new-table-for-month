module "heatmap_japan_dev" {
  source = "../../"

  # Basic configuration
  aws_region   = "ap-northeast-1"
  environment  = "dev"
  project_name = "heatmap-japan"

  # Commented out - Valkey network configuration
  # vpc_id                     = "vpc-06b9f7c3aaf0a5e27"
  # subnet_ids                 = ["subnet-05c9d3074a0ca7f0d", "subnet-0cf7d53eefe0c5e11"]
  # allowed_security_group_ids = ["sg-053f468d46fbc68b5", "sg-0177eadf990472b3e"]

  # Commented out - Valkey configuration for dev
  # valkey_node_type                       = "cache.t4g.micro"
  # valkey_num_cache_nodes                 = 1
  # valkey_engine_version                  = "8.1"
  # valkey_multi_az_enabled                = false
  # valkey_at_rest_encryption_enabled      = false
  # valkey_transit_encryption_enabled      = false
  # valkey_snapshot_retention_limit        = 1
  # valkey_snapshot_window                 = "03:00-04:00"
  # valkey_maintenance_window              = "sun:04:00-sun:05:00"
  # valkey_enable_cloudwatch_alarms        = false

  # Lambda functions configuration (if needed)
  lambda_functions = {}
}
