terraform {
  backend "s3" {
    bucket         = "faber-terraform-state-develop"
    key            = "heatmap-japan/dev/terraform.tfstate"
    region         = "ap-northeast-1"
    encrypt        = true
    dynamodb_table = "faber-terraform-lock"
  }
}