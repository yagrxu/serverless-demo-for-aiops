#!/usr/bin/env bash
# Create the six DynamoDB tables inside DynamoDB Local (docker-compose ddb service).
# Idempotent: existing tables are skipped.
set -euo pipefail

ENDPOINT="${DDB_ENDPOINT:-http://localhost:8001}"
REGION="${AWS_REGION:-us-east-1}"

export AWS_ACCESS_KEY_ID=local
export AWS_SECRET_ACCESS_KEY=local
export AWS_DEFAULT_REGION="$REGION"

ddb() { aws dynamodb --endpoint-url "$ENDPOINT" "$@"; }

create_if_missing() {
  local name="$1"; shift
  if ddb describe-table --table-name "$name" >/dev/null 2>&1; then
    echo "   exists: $name"
  else
    echo "   create: $name"
    ddb create-table --table-name "$name" "$@" --billing-mode PAY_PER_REQUEST >/dev/null
  fi
}

echo ">> endpoint: $ENDPOINT"

create_if_missing CatProfiles \
  --attribute-definitions AttributeName=cat_id,AttributeType=S \
  --key-schema AttributeName=cat_id,KeyType=HASH

create_if_missing Devices \
  --attribute-definitions AttributeName=device_id,AttributeType=S AttributeName=cat_id,AttributeType=S \
  --key-schema AttributeName=device_id,KeyType=HASH \
  --global-secondary-indexes \
    'IndexName=by-cat,KeySchema=[{AttributeName=cat_id,KeyType=HASH}],Projection={ProjectionType=ALL}'

create_if_missing DeviceTelemetry \
  --attribute-definitions AttributeName=device_id,AttributeType=S AttributeName=ts,AttributeType=S \
  --key-schema AttributeName=device_id,KeyType=HASH AttributeName=ts,KeyType=RANGE

create_if_missing FeedingEvents \
  --attribute-definitions AttributeName=cat_id,AttributeType=S AttributeName=ts,AttributeType=S \
  --key-schema AttributeName=cat_id,KeyType=HASH AttributeName=ts,KeyType=RANGE

create_if_missing HealthMetrics \
  --attribute-definitions AttributeName=cat_id,AttributeType=S AttributeName=ts,AttributeType=S \
  --key-schema AttributeName=cat_id,KeyType=HASH AttributeName=ts,KeyType=RANGE

create_if_missing HealthAlerts \
  --attribute-definitions AttributeName=cat_id,AttributeType=S AttributeName=alert_id,AttributeType=S \
  --key-schema AttributeName=cat_id,KeyType=HASH AttributeName=alert_id,KeyType=RANGE

create_if_missing CatNameIndex \
  --attribute-definitions AttributeName=name,AttributeType=S \
  --key-schema AttributeName=name,KeyType=HASH

echo ">> done"
ddb list-tables
