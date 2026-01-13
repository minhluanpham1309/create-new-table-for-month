terraform {
  backend "s3" {
    bucket         = "faber-terraform-state-production"
    key            = "heatmap-japan/prod/terraform.tfstate"
    region         = "ap-northeast-1"
    encrypt        = true
    dynamodb_table = "faber-terraform-lock"
  }
}