resource "aws_elasticache_subnet_group" "valkey" {
  name       = "${var.project_name}-valkey-subnet-group"
  subnet_ids = var.subnet_ids

  tags = merge(
    var.tags,
    {
      Name = "${var.project_name}-valkey-subnet-group"
    }
  )
}

resource "aws_security_group" "valkey" {
  name_prefix = "${var.project_name}-valkey"
  vpc_id      = var.vpc_id
  description = "Security group for Valkey cluster"

  ingress {
    from_port       = var.port
    to_port         = var.port
    protocol        = "tcp"
    security_groups = var.allowed_security_group_ids
    description     = "Valkey port access from EC2 instances only"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "All outbound traffic"
  }

  tags = merge(
    var.tags,
    {
      Name = "${var.project_name}-valkey-sg"
    }
  )

  lifecycle {
    create_before_destroy = true
  }
}

# Using default parameter group for simplicity

resource "aws_elasticache_replication_group" "valkey" {
  replication_group_id = "${var.project_name}-valkey"
  description          = "${var.project_name} Valkey cluster"
  
  # Engine configuration
  engine         = "valkey"
  engine_version = var.engine_version
  node_type      = var.node_type
  port          = var.port
  
  # Cluster configuration
  num_cache_clusters         = var.num_cache_nodes
  automatic_failover_enabled = var.num_cache_nodes > 1
  multi_az_enabled          = var.multi_az_enabled
  
  # Network configuration
  subnet_group_name  = aws_elasticache_subnet_group.valkey.name
  security_group_ids = [aws_security_group.valkey.id]
  
  # Backup configuration
  snapshot_retention_limit = var.snapshot_retention_limit
  snapshot_window         = var.snapshot_window
  maintenance_window      = var.maintenance_window
  
  # Security configuration
  at_rest_encryption_enabled = var.at_rest_encryption_enabled
  transit_encryption_enabled = var.transit_encryption_enabled
  
  # Logging
  log_delivery_configuration {
    destination      = aws_cloudwatch_log_group.valkey_slow.name
    destination_type = "cloudwatch-logs"
    log_format       = "text"
    log_type         = "slow-log"
  }

  tags = merge(
    var.tags,
    {
      Name = "${var.project_name}-valkey"
    }
  )

  depends_on = [
    aws_elasticache_subnet_group.valkey,
    aws_security_group.valkey,
    aws_cloudwatch_log_group.valkey_slow
  ]
}

resource "aws_cloudwatch_log_group" "valkey_slow" {
  name              = "/aws/elasticache/valkey/${var.project_name}/slow-log"
  retention_in_days = var.log_retention_in_days

  tags = merge(
    var.tags,
    {
      Name = "${var.project_name}-valkey-slow-log"
    }
  )
}

# CloudWatch Alarms - Simple replication group level monitoring
resource "aws_cloudwatch_metric_alarm" "valkey_cpu" {
  count = var.enable_cloudwatch_alarms ? 1 : 0

  alarm_name          = "${var.project_name}-valkey-high-cpu"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "CPUUtilization"
  namespace           = "AWS/ElastiCache"
  period              = "300"
  statistic           = "Average"
  threshold           = var.cpu_alarm_threshold
  alarm_description   = "This metric monitors valkey cpu utilization"
  alarm_actions       = var.alarm_actions

  dimensions = {
    ReplicationGroupId = aws_elasticache_replication_group.valkey.id
  }

  tags = var.tags
}

resource "aws_cloudwatch_metric_alarm" "valkey_memory" {
  count = var.enable_cloudwatch_alarms ? 1 : 0

  alarm_name          = "${var.project_name}-valkey-high-memory"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "DatabaseMemoryUsagePercentage"
  namespace           = "AWS/ElastiCache"
  period              = "300"
  statistic           = "Average"
  threshold           = var.memory_alarm_threshold
  alarm_description   = "This metric monitors valkey memory usage percentage"
  alarm_actions       = var.alarm_actions

  dimensions = {
    ReplicationGroupId = aws_elasticache_replication_group.valkey.id
  }

  tags = var.tags
}