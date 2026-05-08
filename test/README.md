# Test Scripts

Scripts for verifying and seeding the cloud deployment.

## Verify deployment

```bash
./test/verify-cloud.sh
```

Checks each layer:
1. DynamoDB tables exist
2. API Gateway responds
3. Lambda handlers work (create + read)
4. CloudFront serves UI
5. AgentCore Runtimes exist

## Seed cloud data

```bash
# Step 1: Seed via API (cats, devices, feedings)
./test/seed-cloud.sh

# Step 2: Seed via DynamoDB directly (health metrics, alerts, name index)
./test/seed-cloud-ddb.sh
```

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `API_URL` | `https://thoctzvibl.execute-api.us-east-1.amazonaws.com/prod` | API Gateway URL |
| `UI_URL` | `https://d1huvxr31jy2lv.cloudfront.net` | CloudFront URL |
| `AWS_REGION` | `us-east-1` | AWS region |
