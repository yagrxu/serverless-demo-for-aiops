# AWS Environment

## Region

- **All stacks deploy to `us-east-1`**. Always use `--region us-east-1` when running AWS CLI commands for this project.

## Bedrock Model ID

- **Always use the cross-region inference profile prefix `us.`** for model IDs.
- Default model: `us.anthropic.claude-haiku-4-5-20251001-v1:0`
- The bare model ID (without `us.` prefix) is NOT supported for on-demand throughput.
- This applies to: agent source code defaults, CDK environment variables, tests, and trafgen profiles.

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
1. `aiops-cat-demo-observability` (consumes refs from api, data, ui — must go first)
2. `aiops-cat-demo-fargate` (or `aiops-cat-demo-apprunner`)
3. `aiops-cat-demo-agents`
4. `aiops-cat-demo-gateway`
5. `aiops-cat-demo-ui`
6. `aiops-cat-demo-api`
7. `aiops-cat-demo-ecr`
8. `aiops-cat-demo-data` (last — other stacks reference its tables)
