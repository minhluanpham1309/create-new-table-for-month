output "vpc_endpoint_id" {
  description = "VPC endpoint ID"
  value       = aws_vpc_endpoint.this.id
}

output "vpc_endpoint_arn" {
  description = "VPC endpoint ARN"
  value       = aws_vpc_endpoint.this.arn
}

output "vpc_endpoint_dns_entry" {
  description = "VPC endpoint DNS entries"
  value       = aws_vpc_endpoint.this.dns_entry
}

output "vpc_endpoint_network_interface_ids" {
  description = "Network interface IDs for Interface endpoints"
  value       = aws_vpc_endpoint.this.network_interface_ids
}