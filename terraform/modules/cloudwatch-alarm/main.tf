# ============================================================
# cloudwatch-alarm module — main.tf
# ============================================================

# ----------------------------------------------------------------
# Locals — SNS ARNs fed to every alarm action
# ----------------------------------------------------------------
locals {
  all_action_arns = var.notification.existing_sns_topic_arns == null ? [] : [var.notification.existing_sns_topic_arns]
}

# ================================================================
# CloudWatch Metric Alarms
# ================================================================
resource "aws_cloudwatch_metric_alarm" "this" {
  for_each = var.alarms

  alarm_name        = each.key
  alarm_description = each.value.alarm_description
  namespace         = each.value.namespace
  metric_name       = each.value.metric_name
  dimensions        = each.value.dimensions

  # Threshold
  threshold           = each.value.threshold
  comparison_operator = each.value.comparison_operator

  # Period / evaluation
  period              = each.value.period
  evaluation_periods  = each.value.evaluation_periods
  datapoints_to_alarm = each.value.datapoints_to_alarm != null ? each.value.datapoints_to_alarm : each.value.evaluation_periods

  # Statistic — use extended_statistic (e.g. p99) when provided, else plain statistic
  statistic          = each.value.extended_statistic == null ? each.value.statistic : null
  extended_statistic = each.value.extended_statistic

  # Missing data behaviour
  treat_missing_data = each.value.treat_missing_data

  # Notifications
  alarm_actions = local.all_action_arns
  ok_actions    = each.value.ok_actions_enabled ? local.all_action_arns : []

  tags = merge(var.tags, { Name = each.key })
}
