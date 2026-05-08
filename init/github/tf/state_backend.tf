# state_backend.tf — S3 bucket and DynamoDB table for remote state (both accounts)

# ==============================================================================
# TEST Account State Backend
# ==============================================================================

resource "aws_s3_bucket" "terraform_state_test" {
  provider = aws.test

  bucket = var.environments["test"].state_bucket_name

  lifecycle {
    prevent_destroy = true
  }

  tags = merge(var.tags, {
    Name        = var.environments["test"].state_bucket_name
    Environment = "test"
  })
}

resource "aws_s3_bucket_versioning" "terraform_state_test" {
  provider = aws.test

  bucket = aws_s3_bucket.terraform_state_test.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "terraform_state_test" {
  provider = aws.test

  bucket = aws_s3_bucket.terraform_state_test.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "aws:kms"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "terraform_state_test" {
  provider = aws.test

  bucket = aws_s3_bucket.terraform_state_test.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_dynamodb_table" "terraform_locks_test" {
  provider = aws.test

  name         = var.environments["test"].lock_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }

  lifecycle {
    prevent_destroy = true
  }

  tags = merge(var.tags, {
    Name        = var.environments["test"].lock_table_name
    Environment = "test"
  })
}

# ==============================================================================
# RELEASE Account State Backend
# ==============================================================================

resource "aws_s3_bucket" "terraform_state_release" {
  provider = aws.release

  bucket = var.environments["release"].state_bucket_name

  lifecycle {
    prevent_destroy = true
  }

  tags = merge(var.tags, {
    Name        = var.environments["release"].state_bucket_name
    Environment = "release"
  })
}

resource "aws_s3_bucket_versioning" "terraform_state_release" {
  provider = aws.release

  bucket = aws_s3_bucket.terraform_state_release.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "terraform_state_release" {
  provider = aws.release

  bucket = aws_s3_bucket.terraform_state_release.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "aws:kms"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "terraform_state_release" {
  provider = aws.release

  bucket = aws_s3_bucket.terraform_state_release.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_dynamodb_table" "terraform_locks_release" {
  provider = aws.release

  name         = var.environments["release"].lock_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }

  lifecycle {
    prevent_destroy = true
  }

  tags = merge(var.tags, {
    Name        = var.environments["release"].lock_table_name
    Environment = "release"
  })
}
