variable "topic_name" {
  description = "The name of the SNS topic"
  type        = string
}

variable "display_name" {
  description = "The display name for the SNS topic"
  type        = string
  default     = null
}

variable "subscription_emails" {
  description = "List of email addresses to subscribe to SNS topic"
  type        = list(string)
  default     = []
}

variable "tags" {
  description = "A map of tags to add to all resources"
  type        = map(string)
  default     = {}
}
