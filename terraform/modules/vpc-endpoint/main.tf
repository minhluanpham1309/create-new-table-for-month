# VPC Endpoint
resource "aws_vpc_endpoint" "this" {
  vpc_id             = var.vpc_id
  service_name       = var.service_name
  vpc_endpoint_type  = var.vpc_endpoint_type
  
  # For Interface endpoints
  subnet_ids         = var.vpc_endpoint_type == "Interface" ? var.subnet_ids : null
  security_group_ids = var.vpc_endpoint_type == "Interface" ? var.security_group_ids : null
  
  # For Gateway endpoints
  route_table_ids    = var.vpc_endpoint_type == "Gateway" ? var.route_table_ids : null
  
  # DNS configuration (for Interface endpoints)
  private_dns_enabled = var.vpc_endpoint_type == "Interface" ? var.private_dns_enabled : null
  
  # Policy
  policy = var.policy
  
  tags = merge(
    var.tags,
    {
      Name = "${var.project_name}-${var.endpoint_name}"
    }
  )
}