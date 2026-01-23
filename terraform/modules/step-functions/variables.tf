variable "state_name" {
  description = "Name of the Step Functions state machine"
  type        = string
}

variable "definition" {
  description = "Amazon States Language definition of the state machine"
  type        = string

  validation {
    condition     = try(jsondecode(var.definition), null) != null
    error_message = "The Step Functions state machine definition must be valid JSON."
  }
}

# State machine configuration
variable "state_machine_type" {
  description = "Type of state machine (STANDARD or EXPRESS)"
  type        = string
  default     = "STANDARD"

  validation {
    condition     = contains(["STANDARD", "EXPRESS"], var.state_machine_type)
    error_message = "State machine type must be either STANDARD or EXPRESS."
  }
}

# Tags
variable "tags" {
  description = "Additional tags"
  type        = map(string)
  default     = {}
}

variable "role_arn" {
  description = "ARN of the IAM role for Step Function execution. If set, module will use this role."
  type        = string
  default     = null
}
