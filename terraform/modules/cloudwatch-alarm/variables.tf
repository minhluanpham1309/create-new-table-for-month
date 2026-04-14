# ============================================================
# cloudwatch-alarm module — variables.tf
# ============================================================

variable "name" {
  description = "Name used for every alarm name and resource Name tag"
  type        = string
}

# ----------------------------------------------------------------
# Alarms map
# ----------------------------------------------------------------
variable "alarms" {
  description = <<-EOT
    Map of CloudWatch metric alarm definitions.
    Key = logical alarm name (appended to name).

    Supported comparison_operator values:
      GreaterThanOrEqualToThreshold | GreaterThanThreshold |
      LessThanThreshold | LessThanOrEqualToThreshold |
      GreaterThanUpperThreshold | LessThanLowerThreshold

    Common namespaces:
      AWS/Lambda | AWS/ElastiCache | AWS/RDS | AWS/EC2 | custom
  EOT
  type = map(object({
    # --- what to measure ---
    namespace   = string
    metric_name = string
    dimensions  = optional(map(string), {})

    # --- threshold ---
    threshold           = number
    comparison_operator = optional(string, "GreaterThanOrEqualToThreshold")

    # --- period / evaluation ---
    period              = optional(number, 300) # seconds
    evaluation_periods  = optional(number, 2)
    datapoints_to_alarm = optional(number, null) # defaults to evaluation_periods when null
    statistic           = optional(string, "Average")
    extended_statistic  = optional(string, null) # e.g. "p99" – use instead of statistic

    # --- behavior ---
    treat_missing_data = optional(string, "missing") # missing | notBreaching | breaching | ignore
    ok_actions_enabled = optional(bool, false)       # send OK notification as well

    # --- description ---
    alarm_description = optional(string, "")
  }))
}

# ----------------------------------------------------------------
# Notification destinations
# ----------------------------------------------------------------
variable "notification" {
  description = <<-EOT
    Controls where alarm notifications are sent.
    Provide existing_sns_topic_arns to reuse an SNS topic created elsewhere.
  EOT
  type = object({
    existing_sns_topic_arns = optional(string, null)
  })
  default = {}
}

# ----------------------------------------------------------------
# Tags
# ----------------------------------------------------------------
variable "tags" {
  description = "A map of tags applied to all resources"
  type        = map(string)
  default     = {}
}
