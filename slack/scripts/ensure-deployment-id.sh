#!/usr/bin/env bash
#
# Ensure a stable, per-deployment random id exists in SSM Parameter Store and
# echo it to stdout. The id is used as a suffix for the Slack Worker Lambda's
# execution role name so that:
#   - multiple independent deployments in the same account don't collide, and
#   - the DevOps Agent operator role's trust policy can be scoped to exactly
#     this deployment's worker role (see update-operator-trust.sh).
#
# Idempotent: if the parameter already exists, its value is reused.
#
# Usage:
#   slack/scripts/ensure-deployment-id.sh [--profile <aws-profile>] [--region <region>]
#
# Output (stdout): the deployment id (e.g. "a1b2c3d4")
set -euo pipefail

PROFILE=""
REGION="us-east-1"
PARAM_NAME="/aiops-cat-demo/slack/deployment-id"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile) PROFILE="$2"; shift 2 ;;
    --region)  REGION="$2";  shift 2 ;;
    --param)   PARAM_NAME="$2"; shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

AWS=(aws)
[[ -n "$PROFILE" ]] && AWS+=(--profile "$PROFILE")
AWS+=(--region "$REGION")

# Try to read an existing id.
if existing=$("${AWS[@]}" ssm get-parameter --name "$PARAM_NAME" \
      --query 'Parameter.Value' --output text 2>/dev/null); then
  if [[ -n "$existing" && "$existing" != "None" ]]; then
    echo "$existing"
    exit 0
  fi
fi

# Generate a new 8-hex-char id and store it.
NEW_ID="$(openssl rand -hex 4)"
"${AWS[@]}" ssm put-parameter \
  --name "$PARAM_NAME" \
  --type String \
  --value "$NEW_ID" \
  --description "Random suffix for the aiops-cat-demo Slack Worker Lambda role (per deployment)" \
  --no-overwrite >/dev/null

echo "$NEW_ID"
