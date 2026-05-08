variable "project_name" {
  type        = string
  description = "Project name used for resource naming"
  default     = "aiops-demo"
}

variable "github_org" {
  type        = string
  description = "GitHub organization or username"
}

variable "github_repo" {
  type        = string
  description = "GitHub repository name (without org prefix)"
}

variable "environments" {
  type = map(object({
    aws_profile       = string
    aws_region        = string
    branch            = string
    environment_name  = string
    state_bucket_name = string
    lock_table_name   = string
  }))
  description = "Map of environment configurations (test, release) each targeting a different AWS account"
}

variable "tags" {
  type        = map(string)
  description = "Common tags for all resources"
  default = {
    Project   = "aiops-demo"
    ManagedBy = "terraform"
    Component = "oidc-bootstrap"
  }
}
