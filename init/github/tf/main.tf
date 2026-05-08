# main.tf — OIDC Identity Provider + IAM Role for GitHub Actions (dual-account)

# ==============================================================================
# TEST Account
# ==============================================================================

data "tls_certificate" "github_test" {
  url = "https://token.actions.githubusercontent.com/.well-known/openid-configuration"
}

resource "aws_iam_openid_connect_provider" "github_test" {
  provider = aws.test

  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.github_test.certificates[0].sha1_fingerprint]

  tags = merge(var.tags, {
    Name        = "${var.project_name}-github-oidc"
    Environment = "test"
  })
}

resource "aws_iam_role" "github_actions_test" {
  provider = aws.test

  name = "${var.project_name}-github-actions-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Federated = aws_iam_openid_connect_provider.github_test.arn
        }
        Action = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = {
            "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          }
          StringLike = {
            "token.actions.githubusercontent.com:sub" = [
              "repo:${var.github_org}/${var.github_repo}:ref:refs/heads/${var.environments["test"].branch}",
              "repo:${var.github_org}/${var.github_repo}:environment:${var.environments["test"].environment_name}"
            ]
          }
        }
      }
    ]
  })

  tags = merge(var.tags, {
    Name        = "${var.project_name}-github-actions-role"
    Environment = "test"
  })
}

# ==============================================================================
# RELEASE (Production) Account
# ==============================================================================

data "tls_certificate" "github_release" {
  url = "https://token.actions.githubusercontent.com/.well-known/openid-configuration"
}

resource "aws_iam_openid_connect_provider" "github_release" {
  provider = aws.release

  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.github_release.certificates[0].sha1_fingerprint]

  tags = merge(var.tags, {
    Name        = "${var.project_name}-github-oidc"
    Environment = "release"
  })
}

resource "aws_iam_role" "github_actions_release" {
  provider = aws.release

  name = "${var.project_name}-github-actions-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Federated = aws_iam_openid_connect_provider.github_release.arn
        }
        Action = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = {
            "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          }
          StringLike = {
            "token.actions.githubusercontent.com:sub" = [
              "repo:${var.github_org}/${var.github_repo}:ref:refs/heads/${var.environments["release"].branch}",
              "repo:${var.github_org}/${var.github_repo}:environment:${var.environments["release"].environment_name}"
            ]
          }
        }
      }
    ]
  })

  tags = merge(var.tags, {
    Name        = "${var.project_name}-github-actions-role"
    Environment = "release"
  })
}
