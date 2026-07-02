# scripts/

Organized by purpose:

- `scenarios/` — one-shot deploys that inject a specific failure mode
  - `01-latency.sh`
  - `02-wrong-ids.sh`
  - `03-lambda-throttling.sh`
  - `04-dynamodb-throttling.sh`
  - `05-s3-access-errors.sh`

- `load/` — traffic generators you run against a deployed API Gateway URL
  - `basic.sh <api-url>`
  - `lambda-throttle.sh <api-url>`
  - `dynamodb-throttle.sh <api-url>`

GitHub Actions / AWS plumbing (OIDC providers, deploy roles, state buckets) is provisioned via Terraform in [`init/github/tf/`](../init/github/tf/).
