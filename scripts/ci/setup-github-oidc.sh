#!/usr/bin/env bash
# Sets up one AWS account's side of the GitHub Actions OIDC trust.
#
# Run this ONCE per AWS account / GitHub environment pair.
#
# Examples:
#   # test account (cloudops-demo profile) -> 'test' GitHub environment:
#   AWS_PROFILE=cloudops-demo GH_ENV=test ./scripts/ci/setup-github-oidc.sh
#
#   # production account (default profile) -> 'release' GitHub environment:
#   AWS_PROFILE=default GH_ENV=release ./scripts/ci/setup-github-oidc.sh

set -euo pipefail

AWS_PROFILE="${AWS_PROFILE:-cloudops-demo}"
AWS_REGION="${AWS_REGION:-us-east-1}"
GITHUB_REPO="${GITHUB_REPO:-yagrxu/serverless-demo-for-aiops}"
GH_ENV="${GH_ENV:-test}"
ROLE_NAME="${ROLE_NAME:-gha-serverless-demo-${GH_ENV}}"

export AWS_PROFILE AWS_REGION

echo ">> AWS profile: $AWS_PROFILE   region: $AWS_REGION"
echo ">> GitHub repo: $GITHUB_REPO    environment: $GH_ENV"
echo ">> Role name:   $ROLE_NAME"

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
OIDC_ARN="arn:aws:iam::${ACCOUNT_ID}:oidc-provider/token.actions.githubusercontent.com"
echo ">> AWS account: $ACCOUNT_ID"

# --- 1. OIDC provider (idempotent) ------------------------------------------
if aws iam get-open-id-connect-provider --open-id-connect-provider-arn "$OIDC_ARN" >/dev/null 2>&1; then
  echo ">> OIDC provider already exists — skipping"
else
  echo ">> Creating GitHub OIDC provider"
  aws iam create-open-id-connect-provider \
    --url https://token.actions.githubusercontent.com \
    --client-id-list sts.amazonaws.com \
    --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1 \
    >/dev/null
fi

# --- 2. Trust policy scoped to a GitHub environment -------------------------
TRUST_POLICY=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "Federated": "${OIDC_ARN}" },
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {
        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
        "token.actions.githubusercontent.com:sub": "repo:${GITHUB_REPO}:environment:${GH_ENV}"
      }
    }
  }]
}
EOF
)

# --- 3. Role (idempotent) ----------------------------------------------------
if aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  echo ">> Role $ROLE_NAME exists — updating trust policy"
  aws iam update-assume-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-document "$TRUST_POLICY"
else
  echo ">> Creating role $ROLE_NAME"
  aws iam create-role \
    --role-name "$ROLE_NAME" \
    --assume-role-policy-document "$TRUST_POLICY" \
    --description "GitHub Actions deploy role for ${GITHUB_REPO} (${GH_ENV})" \
    >/dev/null
fi

echo ">> Attaching AdministratorAccess (test-only project)"
aws iam attach-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-arn arn:aws:iam::aws:policy/AdministratorAccess

ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"
echo ">> Role ARN: $ROLE_ARN"

# --- 4. Register the ARN as a GitHub *environment variable* -----------------
if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  echo ">> Ensuring GitHub environment '$GH_ENV' exists"
  gh api -X PUT "repos/${GITHUB_REPO}/environments/${GH_ENV}" >/dev/null

  echo ">> Setting AWS_DEPLOY_ROLE_ARN variable on environment '$GH_ENV'"
  gh variable set AWS_DEPLOY_ROLE_ARN \
    --repo "$GITHUB_REPO" \
    --env "$GH_ENV" \
    --body "$ROLE_ARN"
  echo ">> Variable set."
else
  echo "!! gh CLI not available — add it manually:"
  echo "   Settings -> Environments -> $GH_ENV -> Variables -> AWS_DEPLOY_ROLE_ARN"
  echo "   Value: $ROLE_ARN"
fi

echo
echo ">> Done. Push to the '$GH_ENV' branch to trigger a deploy."
