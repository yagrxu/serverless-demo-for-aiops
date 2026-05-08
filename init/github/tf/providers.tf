terraform {
  required_version = ">= 1.7.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # This bootstrap project uses LOCAL state intentionally.
  # It must exist before the S3 backend is available.
  # State file should be committed or stored securely.
}

# Provider for the TEST account
provider "aws" {
  alias   = "test"
  profile = var.environments["test"].aws_profile
  region  = var.environments["test"].aws_region

  default_tags {
    tags = var.tags
  }
}

# Provider for the RELEASE (production) account
provider "aws" {
  alias   = "release"
  profile = var.environments["release"].aws_profile
  region  = var.environments["release"].aws_region

  default_tags {
    tags = var.tags
  }
}
