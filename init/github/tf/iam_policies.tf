# iam_policies.tf — Policies attached to the GitHub Actions roles (both accounts)

# ==============================================================================
# TEST Account Policies
# ==============================================================================

resource "aws_iam_policy" "terraform_state_test" {
  provider = aws.test

  name        = "${var.project_name}-terraform-state-access"
  description = "Allow access to Terraform state bucket and lock table"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "S3StateAccess"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:ListBucket",
        ]
        Resource = [
          aws_s3_bucket.terraform_state_test.arn,
          "${aws_s3_bucket.terraform_state_test.arn}/*",
        ]
      },
      {
        Sid    = "DynamoDBLockAccess"
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:DeleteItem",
        ]
        Resource = aws_dynamodb_table.terraform_locks_test.arn
      }
    ]
  })

  tags = merge(var.tags, { Environment = "test" })
}

# AdministratorAccess for demo — replace with scoped policies for production
resource "aws_iam_role_policy_attachment" "admin_access_test" {
  provider = aws.test

  role       = aws_iam_role.github_actions_test.name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}

resource "aws_iam_role_policy_attachment" "terraform_state_test" {
  provider = aws.test

  role       = aws_iam_role.github_actions_test.name
  policy_arn = aws_iam_policy.terraform_state_test.arn
}

# ==============================================================================
# RELEASE Account Policies
# ==============================================================================

resource "aws_iam_policy" "terraform_state_release" {
  provider = aws.release

  name        = "${var.project_name}-terraform-state-access"
  description = "Allow access to Terraform state bucket and lock table"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "S3StateAccess"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:ListBucket",
        ]
        Resource = [
          aws_s3_bucket.terraform_state_release.arn,
          "${aws_s3_bucket.terraform_state_release.arn}/*",
        ]
      },
      {
        Sid    = "DynamoDBLockAccess"
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:DeleteItem",
        ]
        Resource = aws_dynamodb_table.terraform_locks_release.arn
      }
    ]
  })

  tags = merge(var.tags, { Environment = "release" })
}

# AdministratorAccess for demo — replace with scoped policies for production
resource "aws_iam_role_policy_attachment" "admin_access_release" {
  provider = aws.release

  role       = aws_iam_role.github_actions_release.name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}

resource "aws_iam_role_policy_attachment" "terraform_state_release" {
  provider = aws.release

  role       = aws_iam_role.github_actions_release.name
  policy_arn = aws_iam_policy.terraform_state_release.arn
}
