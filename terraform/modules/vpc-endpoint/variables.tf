# Required variables for the vpc-endpoint module
variable "project_name" {
  description = "Project name"
  type        = string
}

variable "endpoint_name" {
  description = "Name of the VPC endpoint"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID where the endpoint will be created"
  type        = string
}

variable "service_name" {
  description = "The service name (e.g., com.amazonaws.region.s3, com.amazonaws.region.secretsmanager)"
  type        = string
}

variable "vpc_endpoint_type" {
  description = "The VPC endpoint type (Gateway or Interface)"
  type        = string
  default     = "Interface"
  
  validation {
    condition     = contains(["Gateway", "Interface"], var.vpc_endpoint_type)
    error_message = "VPC endpoint type must be either 'Gateway' or 'Interface'."
  }
}

# Interface endpoint configuration
variable "subnet_ids" {
  description = "List of subnet IDs (required for Interface endpoints)"
  type        = list(string)
  default     = null
}

variable "security_group_ids" {
  description = "List of security group IDs (for Interface endpoints)"
  type        = list(string)
  default     = null
}

variable "private_dns_enabled" {
  description = "Whether to enable private DNS for Interface endpoints"
  type        = bool
  default     = true
}

# Gateway endpoint configuration
variable "route_table_ids" {
  description = "List of route table IDs (required for Gateway endpoints)"
  type        = list(string)
  default     = null
}

# Policy
variable "policy" {
  description = "Policy to attach to the endpoint"
  type        = string
  default     = null
}

# Tags
variable "tags" {
  description = "Additional tags to apply to all resources in this module"
  type        = map(string)
  default     = {}
}
