#!/usr/bin/env bash
#
# Add a trust-policy statement to the DevOps Agent operator role allowing the
# Slack Worker Lambda's execution role to assume it (with session tagging).
#
# IAM rejects a trust policy that names a principal role ARN before that role
# exists ("Invalid principal in policy"). To make approach A work BEFORE the
# CDK deploy, the statement uses the account root as the principal and an
# `aws:PrincipalArn` ArnLike condition scoped to exactly this deployment's
# worker role name (aiops-cat-demo-slack-worker-<deployment-id>). This is valid
# immediately, survives role re-creation, and stays scoped to one role.
#
# Idempotent: re-running with the same deployment id replaces the matching
# statement (keyed by Sid) rather than appending duplicates.
#
# Usage:
#   slack/scripts/update-operator-trust.sh \
#     --operator-role-arn <arn> \
#     --deployment-id <id> \
#     [--profile <aws-profile>] [--region <region>]
set -euo pipefail

PROFILE=""
REGION="us-east-1"
OPERATOR_ROLE_ARN=""
DEPLOYMENT_ID=""
PROJECT="aiops-cat-demo"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --operator-role-arn) OPERATOR_ROLE_ARN="$2"; shift 2 ;;
    --deployment-id)     DEPLOYMENT_ID="$2";     shift 2 ;;
    --profile)           PROFILE="$2";           shift 2 ;;
    --region)            REGION="$2";            shift 2 ;;
    --project)           PROJECT="$2";           shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

[[ -z "$OPERATOR_ROLE_ARN" ]] && { echo "--operator-role-arn required" >&2; exit 1; }
[[ -z "$DEPLOYMENT_ID" ]]     && { echo "--deployment-id required" >&2; exit 1; }

AWS=(aws)
[[ -n "$PROFILE" ]] && AWS+=(--profile "$PROFILE")
AWS+=(--region "$REGION")

ROLE_NAME="${OPERATOR_ROLE_ARN##*/}"
ACCOUNT_ID="$("${AWS[@]}" sts get-caller-identity --query Account --output text)"
WORKER_ROLE_NAME="${PROJECT}-slack-worker-${DEPLOYMENT_ID}"
WORKER_ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${WORKER_ROLE_NAME}"
SID="SlackWorker${DEPLOYMENT_ID}"

echo "Operator role:  $ROLE_NAME" >&2
echo "Worker role:    $WORKER_ROLE_ARN" >&2
echo "Statement Sid:  $SID" >&2

CURRENT="$("${AWS[@]}" iam get-role --role-name "$ROLE_NAME" \
  --query 'Role.AssumeRolePolicyDocument' --output json)"

# Merge: drop any prior statement with the same Sid, then append the new one.
UPDATED="$(python3 - "$CURRENT" "$SID" "$ACCOUNT_ID" "$WORKER_ROLE_ARN" <<'PY'
import json, sys
doc = json.loads(sys.argv[1])
sid, account_id, worker_arn = sys.argv[2], sys.argv[3], sys.argv[4]
stmts = [s for s in doc.get("Statement", []) if s.get("Sid") != sid]
stmts.append({
    "Sid": sid,
    "Effect": "Allow",
    "Principal": {"AWS": f"arn:aws:iam::{account_id}:root"},
    "Action": ["sts:AssumeRole", "sts:TagSession"],
    "Condition": {"ArnLike": {"aws:PrincipalArn": worker_arn}},
})
doc["Statement"] = stmts
print(json.dumps(doc))
PY
)"

"${AWS[@]}" iam update-assume-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-document "$UPDATED"

echo "Trust policy updated: $ROLE_NAME now allows $WORKER_ROLE_ARN to assume it." >&2
