# SNS Topic (STANDARD)
resource "aws_sns_topic" "this" {
  name         = var.topic_name
  display_name = var.display_name
  fifo_topic   = false # Standard topic

  tags = merge(
    var.tags,
    {
      Name = var.topic_name
    }
  )
}

resource "aws_sns_topic_subscription" "email" {
  count     = length(var.subscription_emails)
  topic_arn = aws_sns_topic.this.arn
  protocol  = "email"
  endpoint  = var.subscription_emails[count.index]
}
