module "heatmap_japan_prod" {
  source = "../../"

  # Basic configuration
  aws_region   = "ap-northeast-1"
  environment  = "prod"
  project_name = "heatmap-japan"

  # Commented out - Valkey network configuration
  # vpc_id                     = "vpc-208b8042"
  # subnet_ids                 = ["subnet-c5d6fcb1", "subnet-e1b8eda7"]
  # allowed_security_group_ids = ["sg-52f1d92b", "sg-618cb718"]

  # Commented out - Valkey configuration for prod
  # valkey_node_type                       = "cache.t4g.medium"
  # valkey_num_cache_nodes                 = 2
  # valkey_engine_version                  = "8.1"
  # valkey_multi_az_enabled                = true
  # valkey_at_rest_encryption_enabled      = false
  # valkey_transit_encryption_enabled      = false
  # valkey_snapshot_retention_limit        = 7
  # valkey_snapshot_window                 = "03:00-04:00"
  # valkey_maintenance_window              = "sun:04:00-sun:05:00"
  # valkey_enable_cloudwatch_alarms        = true

  # Lambda functions configuration (if needed)
  lambda_functions = {}
}
