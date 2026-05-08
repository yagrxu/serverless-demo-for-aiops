# outputs.tf — Outputs for both accounts

# ==============================================================================
# TEST Account Outputs
# ==============================================================================

output "test_oidc_provider_arn" {
  description = "ARN of the GitHub Actions OIDC provider (test account)"
  value       = aws_iam_openid_connect_provider.github_test.arn
}

output "test_deploy_role_arn" {
  description = "ARN of the IAM role for GitHub Actions (test account) — set as AWS_DEPLOY_ROLE_ARN in 'test' environment"
  value       = aws_iam_role.github_actions_test.arn
}

output "test_deploy_role_name" {
  description = "Name of the IAM role for GitHub Actions (test account)"
  value       = aws_iam_role.github_actions_test.name
}

output "test_state_bucket_name" {
  description = "S3 bucket name for Terraform remote state (test account)"
  value       = aws_s3_bucket.terraform_state_test.id
}

output "test_state_lock_table_name" {
  description = "DynamoDB table name for Terraform state locking (test account)"
  value       = aws_dynamodb_table.terraform_locks_test.name
}

# ==============================================================================
# RELEASE Account Outputs
# ==============================================================================

output "release_oidc_provider_arn" {
  description = "ARN of the GitHub Actions OIDC provider (release account)"
  value       = aws_iam_openid_connect_provider.github_release.arn
}

output "release_deploy_role_arn" {
  description = "ARN of the IAM role for GitHub Actions (release account) — set as AWS_DEPLOY_ROLE_ARN in 'release' environment"
  value       = aws_iam_role.github_actions_release.arn
}

output "release_deploy_role_name" {
  description = "Name of the IAM role for GitHub Actions (release account)"
  value       = aws_iam_role.github_actions_release.name
}

output "release_state_bucket_name" {
  description = "S3 bucket name for Terraform remote state (release account)"
  value       = aws_s3_bucket.terraform_state_release.id
}

output "release_state_lock_table_name" {
  description = "DynamoDB table name for Terraform state locking (release account)"
  value       = aws_dynamodb_table.terraform_locks_release.name
}
