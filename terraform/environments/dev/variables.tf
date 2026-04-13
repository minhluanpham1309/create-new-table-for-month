variable "lambda_function_name_producer" {
  default = "MonthlyAddingSiteTablesProducer"
}

variable "lambda_function_name_consumer" {
  default = "MonthlyAddingSiteTablesConsumer"
}

variable "sns_topic_monthly_adding_site_tables_notifications" {
  default = "monthly-adding-site-tables-notifications"
}

variable "sfn_name_monthly_adding_site_tables_consumer" {
  default = "monthly-adding-site-tables-consumer"
}

variable "lambda_function_name_delete_heat_map_cache" {
  default = "DeleteHeatMapCache"
}

variable "lambda_function_name_delete_old_data_heat_map" {
  default = "DeleteOldDataHeatMap"
}

variable "lambda_alias" {
  default = "live"
}

variable "lambda_function_name_move_data_to_mysql" {
  default = "MoveDataToMysql"
}

variable "lambda_function_name_check_limit" {
  default = "CheckLimit"
}
