output "endpoint" {
  description = "Valkey cluster endpoint"
  value = coalesce(
    aws_elasticache_replication_group.valkey.configuration_endpoint_address,
    aws_elasticache_replication_group.valkey.primary_endpoint_address
  )
}

output "port" {
  description = "Valkey cluster port"
  value       = aws_elasticache_replication_group.valkey.port
}

output "id" {
  description = "Valkey replication group ID"
  value       = aws_elasticache_replication_group.valkey.id
}

output "arn" {
  description = "Valkey replication group ARN"
  value       = aws_elasticache_replication_group.valkey.arn
}

output "security_group_id" {
  description = "Security group ID"
  value       = aws_security_group.valkey.id
}

output "subnet_group_name" {
  description = "Subnet group name"
  value       = aws_elasticache_subnet_group.valkey.name
}