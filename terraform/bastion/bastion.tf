# bastion.tf

# ========================================
# BASTION INSTANCE
# ========================================
resource "aws_instance" "bastion" {
  ami                    = "ami-0e3ad22ed1c427297"  # Amazon Linux 2023 (ap-northeast-1)
  instance_type          = "t4g.nano"               # ARM-based,  (~$3/month)
  subnet_id              = var.bastion_subnet_id    # into vpc of Valkey
  vpc_security_group_ids = [aws_security_group.bastion.id]
  iam_instance_profile   = aws_iam_instance_profile.bastion.name

  # SSM agent được pre-installed trên Amazon Linux 2023
  user_data = <<-EOF
    #!/bin/bash
    # Đảm bảo SSM agent running
    systemctl enable amazon-ssm-agent
    systemctl start amazon-ssm-agent
  EOF

  tags = {
    Name        = "heatmap-bastion"
    Environment = "dev"
    Purpose     = "Valkey access"
  }
}

# ========================================
# SECURITY GROUP
# ========================================
resource "aws_security_group" "bastion" {
  name        = "heatmap-bastion-sg"
  description = "Security group for bastion host"
  vpc_id      = var.vpc_id

  # Cho phép outbound tới Valkey
  egress {
    from_port   = 6379
    to_port     = 6379
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
    description = "Allow connection to Valkey"
  }

  # Cho phép HTTPS cho SSM
  egress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Allow HTTPS for SSM"
  }

  tags = {
    Name = "heatmap-bastion-sg"
  }
}

# ========================================
# IAM ROLE & POLICIES
# ========================================
resource "aws_iam_instance_profile" "bastion" {
  name = "heatmap-bastion-profile"
  role = aws_iam_role.bastion.name
}

resource "aws_iam_role" "bastion" {
  name = "heatmap-bastion-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name = "heatmap-bastion-role"
  }
}

# Attach SSM policy
resource "aws_iam_role_policy_attachment" "bastion_ssm" {
  role       = aws_iam_role.bastion.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# ========================================
# OUTPUTS
# ========================================
output "bastion_instance_id" {
  description = "Instance ID của bastion host"
  value       = aws_instance.bastion.id
}

output "bastion_private_ip" {
  description = "Private IP của bastion"
  value       = aws_instance.bastion.private_ip
}