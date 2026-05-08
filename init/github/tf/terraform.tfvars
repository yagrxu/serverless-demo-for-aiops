# terraform.tfvars — Dual-account configuration for GitHub Actions OIDC

project_name = "aiops-demo"

# GitHub repository
github_org  = "yagrxu"
github_repo = "serverless-demo-for-aiops"

# Dual-account environment configuration
environments = {
  test = {
    aws_profile       = "default"
    aws_region        = "us-east-1"
    branch            = "test"
    environment_name  = "test"
    state_bucket_name = "aiops-demo-terraform-state-613477150601"
    lock_table_name   = "aiops-demo-terraform-locks"
  }
  release = {
    aws_profile       = "cloudops-demo"
    aws_region        = "us-east-1"
    branch            = "release"
    environment_name  = "release"
    state_bucket_name = "aiops-demo-terraform-state-719821274597"
    lock_table_name   = "aiops-demo-terraform-locks"
  }
}

# Common tags applied to all resources
tags = {
  Project     = "aiops-demo"
  ManagedBy   = "terraform"
  Component   = "oidc-bootstrap"
  Environment = "shared"
}
