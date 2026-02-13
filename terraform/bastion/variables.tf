# bastion-variables.tf
variable "bastion_subnet_id" {
  description = "Subnet ID for bastion"
  type        = string
  # get from AWS Console or CLI
}

variable "vpc_id" {
  description = "VPC ID of Valkey cluster"
  type        = string
}

variable "vpc_cidr" {
  description = "CIDR block of VPC"
  type        = string
}