
# Basic Lambda function - Gọi trực tiếp module lambda-function
module "heatmap_japan_dev" {
  source = "../../"
  environment = "dev"
  aws_region  = "ap-northeast-1"

  lambda_functions = {
    HeatmapLambdaSplitSites = {
      function_name = "HeatmapLambdaSplitSites"
      handler       = "lambda_function.lambda_handler"
      runtime       = "python3.11"

      timeout     = 900
      memory_size = 256

      environment_variables = {
        ENVIRONMENT = "dev"
        LOG_LEVEL   = "INFO"
        SITE_CHUNK_DAYS = 21
        RDS_SECRET_NAME = "rds/db-test-private"
      }

      role_arn = "arn:aws:iam::683918607581:role/excute-lambda"

      create_security_group = false
      vpc_config = {
        vpc_id             = "vpc-08586cd9f6ce3a905"
        subnet_ids         = ["subnet-0ffa21d23c30bbf14", "subnet-09e78cbbf83798d9a", "subnet-0071f6115ba604b19"]
        security_group_ids = ["sg-0ed6967b20d09fea2"]
      }

      # security_group_egress_rules = [{
      #   from_port   = 3306
      #   to_port     = 3306
      #   protocol    = "tcp"
      #   cidr_blocks = ["10.0.1.0/24"]
      #   description = "Allow Lambda to access RDS MySQL"
      # }]
      #
      # rds_security_group_ids = ["sg-0ec24edb38ce58304"]
    }
  }

  step_functions = {
    MonthlyAddingSiteTablesConsumerSF = {
      name        = "monthly-adding-site-tables-consumer"
      definition  = jsonencode({
        "StartAt": "Lambda Invoke",
          "States": {
            "Lambda Invoke": {
              "Type": "Task",
              "Resource": "arn:aws:states:::lambda:invoke",
              "OutputPath": "$.Payload",
              "Parameters": {
                "Payload.$": "$",
                "FunctionName": module.heatmap_japan_dev.lambda_functions["HeatmapLambdaSplitSites"].function_arn
              },
              "End": true
            }
          }
      })
      execution_role_arn = "arn:aws:iam::683918607581:role/CustomMonthlyAddingSiteTablesConsumer"
      enable_logging     = false
    }
  }

  # EventBridge Scheduler to trigger Step Function daily at 9 AM Tokyo time
  eventbridge_rules = {
    daily_step_function_trigger = {
      name                          = "invoke-step-function-daily"
      description                   = "Trigger Step Function at 9:00 Asia/Tokyo every day using EventBridge Scheduler"
      schedule_expression           = "cron(0 9 * * ? *)"
      schedule_expression_timezone  = "Asia/Tokyo"
      enabled                       = true
      scheduler_role_arn            = "arn:aws:iam::683918607581:role/service-role/Amazon_EventBridge_Scheduler_SFN_eb896e981c"

      target = {
        type  = "lambda"
        arn   = module.heatmap_japan_dev.lambda_functions["HeatmapLambdaSplitSites"].function_arn
        input = {}
      }
    }
  }
}
#
# locals {
#   hello_world_sg_id = module.HeatmapLambdaSplitSites.lambda_functions["HeatmapLambdaSplitSites"].security_group_id
# }
#
# data "aws_security_group" "rds" {
#   filter {
#     name   = "group-id"
#     values = ["sg-0ec24edb38ce58304"]
#   }
# }
#
# resource "aws_vpc_security_group_ingress_rule" "lambda_to_rds" {
#   security_group_id            = data.aws_security_group.rds.id
#   from_port                   = 3306
#   to_port                     = 3306
#   ip_protocol                 = "tcp"
#   referenced_security_group_id = local.hello_world_sg_id
#
#   depends_on = [module.HeatmapLambdaSplitSites]
# }

# resource "aws_scheduler_schedule" "invoke_step_function_daily" {
#   name        = "invoke-step-function-daily"
#   description = "Trigger Step Function at 9:00 Tokyo/Asia every day using EventBridge Scheduler"
#
#   flexible_time_window {
#     mode = "OFF"
#   }
#   schedule_expression = "cron(0 9 * * ? *)"
#   schedule_expression_timezone = "Asia/Tokyo"
#   target {
#     arn      = module.example_step_function.state_machine_arn
#     role_arn = "arn:aws:iam::683918607581:role/service-role/Amazon_EventBridge_Scheduler_SFN_eb896e981c"
#     input    = "{}"
#   }
# }
