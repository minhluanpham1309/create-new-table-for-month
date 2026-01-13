# data "aws_elasticache_replication_group" "valkey" {
#   replication_group_id = "heatmap-japan-valkey"
# }
# 
# output "valkey_primary_endpoint" {
#   description = "Valkey primary endpoint (READ/WRITE)"  
#   value       = data.aws_elasticache_replication_group.valkey.primary_endpoint_address
# }
# 
# output "valkey_reader_endpoint" {
#   description = "Valkey reader endpoint (READ-ONLY replicas)"  
#   value       = data.aws_elasticache_replication_group.valkey.reader_endpoint_address
# }
# 
# output "valkey_configuration_endpoint" {
#   description = "Valkey configuration endpoint (cluster mode)"  
#   value       = data.aws_elasticache_replication_group.valkey.configuration_endpoint_address
# }
# 
# output "valkey_member_clusters" {
#   description = "List of all cluster members"
#   value       = data.aws_elasticache_replication_group.valkey.member_clusters
# }
# 
# output "valkey_port" {
#   description = "Valkey port"
#   value       = data.aws_elasticache_replication_group.valkey.port
# }
# 
# output "valkey_num_cache_clusters" {
#   description = "Number of cache clusters"
#   value       = data.aws_elasticache_replication_group.valkey.num_cache_clusters
# }