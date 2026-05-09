# AWS Environment

## Region

- **All stacks deploy to `us-east-1`**. Always use `--region us-east-1` when running AWS CLI commands for this project.

## Accounts & Profiles

| Profile | Account | Purpose |
|---------|---------|---------|
| default | production | `release` branch deploys here |
| cloudops-demo | test | `test` branch deploys here |

## Project Name

- CDK project name: `aiops-cat-demo`
- Stack naming pattern: `aiops-cat-demo-<stack>` (e.g. `aiops-cat-demo-ecr`, `aiops-cat-demo-data`, `aiops-cat-demo-api`)

## Stack Deletion Order

Stacks have dependencies. Delete in this order:
1. `aiops-cat-demo-fargate` (or `aiops-cat-demo-apprunner`)
2. `aiops-cat-demo-agents`
3. `aiops-cat-demo-gateway`
4. `aiops-cat-demo-ui`
5. `aiops-cat-demo-api`
6. `aiops-cat-demo-ecr`
7. `aiops-cat-demo-data` (last — other stacks reference its tables)
