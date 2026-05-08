#!/usr/bin/env bash
# Tear down what setup-github-oidc.sh created for one environment:
#   - detach managed + delete inline policies on the role
#   - delete the role
#   - (optional) delete the GitHub OIDC provider
#   - (if gh is auth'd) remove the env variable from the GitHub environment
#
# Usage:
#   AWS_PROFILE=cloudops-demo GH_ENV=test ./scripts/ci/teardown-github-oidc.sh
#   DELETE_OIDC_PROVIDER=true AWS_PROFILE=cloudops-demo GH_ENV=test ./scripts/ci/teardown-github-oidc.sh
#
# DELETE_OIDC_PROVIDER is off by default — the provider is account-wide.

set -euo pipefail

AWS_PROFILE="${AWS_PROFILE:-cloudops-demo}"
AWS_REGION="${AWS_REGION:-us-east-1}"
GITHUB_REPO="${GITHUB_REPO:-yagrxu/serverless-demo-for-aiops}"
GH_ENV="${GH_ENV:-test}"
ROLE_NAME="${ROLE_NAME:-gha-serverless-demo-${GH_ENV}}"
DELETE_OIDC_PROVIDER="${DELETE_OIDC_PROVIDER:-false}"

export AWS_PROFILE AWS_REGION

echo ">> AWS profile: $AWS_PROFILE   region: $AWS_REGION"
echo ">> Environment: $GH_ENV        role: $ROLE_NAME"

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
OIDC_ARN="arn:aws:iam::${ACCOUNT_ID}:oidc-provider/token.actions.githubusercontent.com"

if aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  echo ">> Detaching managed policies"
  for arn in $(aws iam list-attached-role-policies --role-name "$ROLE_NAME" \
                  --query 'AttachedPolicies[].PolicyArn' --output text); do
    aws iam detach-role-policy --role-name "$ROLE_NAME" --policy-arn "$arn"
    echo "   detached $arn"
  done
  echo ">> Deleting inline policies"
  for name in $(aws iam list-role-policies --role-name "$ROLE_NAME" \
                  --query 'PolicyNames' --output text); do
    aws iam delete-role-policy --role-name "$ROLE_NAME" --policy-name "$name"
    echo "   deleted inline $name"
  done
  echo ">> Deleting role $ROLE_NAME"
  aws iam delete-role --role-name "$ROLE_NAME"
else
  echo ">> Role $ROLE_NAME not found — skipping"
fi

if [[ "$DELETE_OIDC_PROVIDER" == "true" ]]; then
  if aws iam get-open-id-connect-provider --open-id-connect-provider-arn "$OIDC_ARN" >/dev/null 2>&1; then
    echo ">> Deleting OIDC provider $OIDC_ARN"
    aws iam delete-open-id-connect-provider --open-id-connect-provider-arn "$OIDC_ARN"
  fi
else
  echo ">> Leaving OIDC provider in place (set DELETE_OIDC_PROVIDER=true to remove)"
fi

if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  echo ">> Removing AWS_DEPLOY_ROLE_ARN from environment '$GH_ENV'"
  gh variable delete AWS_DEPLOY_ROLE_ARN --repo "$GITHUB_REPO" --env "$GH_ENV" 2>/dev/null \
    && echo "   removed" || echo "   not set (or already removed)"
fi

echo
echo ">> Teardown complete."
