#!/usr/bin/env bash
# Verify each layer of the cloud deployment.
#
# Usage:
#   ./test/verify-cloud.sh
#   API_URL=https://xxx.execute-api.us-east-1.amazonaws.com/prod ./test/verify-cloud.sh
#
# Checks:
#   1. DynamoDB tables exist
#   2. API Gateway responds
#   3. Lambda handlers work (via API)
#   4. CloudFront serves UI
#   5. AgentCore Runtimes exist

set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
API_URL="${API_URL:-https://thoctzvibl.execute-api.us-east-1.amazonaws.com/prod}"
UI_URL="${UI_URL:-https://d1huvxr31jy2lv.cloudfront.net}"

pass() { printf "  \033[1;32m✓\033[0m %s\n" "$*"; }
fail() { printf "  \033[1;31m✗\033[0m %s\n" "$*"; FAILURES=$((FAILURES+1)); }
FAILURES=0

echo "============================================"
echo "  Cloud Deployment Verification"
echo "  Region: $REGION"
echo "  API:    $API_URL"
echo "  UI:     $UI_URL"
echo "============================================"
echo ""

# ---------------------------------------------------------------
# 1. DynamoDB tables
# ---------------------------------------------------------------
echo "--- DynamoDB Tables ---"
EXPECTED_TABLES="CatProfiles CatNameIndex Devices DeviceTelemetry FeedingEvents HealthMetrics HealthAlerts"
ACTUAL_TABLES=$(aws dynamodb list-tables --region "$REGION" --query "TableNames" --output text 2>/dev/null || echo "")

for t in $EXPECTED_TABLES; do
  if echo "$ACTUAL_TABLES" | grep -qw "$t" 2>/dev/null; then
    # Check if table name contains our prefix (CDK generates names with stack prefix)
    pass "Table pattern *$t* found"
  else
    # CDK generates table names like aiops-cat-demo-data-CatProfiles-XXXXX
    if aws dynamodb list-tables --region "$REGION" --query "TableNames" --output text 2>/dev/null | grep -q "$t"; then
      pass "Table *$t* found (CDK-named)"
    else
      fail "Table *$t* NOT found"
    fi
  fi
done
echo ""

# ---------------------------------------------------------------
# 2. API Gateway
# ---------------------------------------------------------------
echo "--- API Gateway ---"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$API_URL/cats" 2>/dev/null || echo "000")
if [[ "$STATUS" == "200" ]]; then
  pass "GET /cats → $STATUS"
else
  fail "GET /cats → $STATUS (expected 200)"
fi

STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$API_URL/devices" 2>/dev/null || echo "000")
if [[ "$STATUS" == "200" ]]; then
  pass "GET /devices → $STATUS"
else
  fail "GET /devices → $STATUS (expected 200)"
fi
echo ""

# ---------------------------------------------------------------
# 3. Lambda handlers (create + read)
# ---------------------------------------------------------------
echo "--- Lambda Handlers (via API) ---"

# Create a test cat
CREATE_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
  -H 'Content-Type: application/json' \
  -d '{"cat_id":"test-verify","name":"TestCat","breed":"test"}' \
  "$API_URL/cats" 2>/dev/null || echo "000")
if [[ "$CREATE_STATUS" == "201" ]]; then
  pass "POST /cats (create) → $CREATE_STATUS"
else
  fail "POST /cats (create) → $CREATE_STATUS (expected 201)"
fi

# Read it back
GET_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$API_URL/cats/test-verify" 2>/dev/null || echo "000")
if [[ "$GET_STATUS" == "200" ]]; then
  pass "GET /cats/test-verify → $GET_STATUS"
else
  fail "GET /cats/test-verify → $GET_STATUS (expected 200)"
fi

# Test feedings (should return 400 without cat_id)
FEED_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$API_URL/feedings" 2>/dev/null || echo "000")
if [[ "$FEED_STATUS" == "400" ]]; then
  pass "GET /feedings (no cat_id) → $FEED_STATUS (expected 400)"
else
  fail "GET /feedings (no cat_id) → $FEED_STATUS (expected 400)"
fi
echo ""

# ---------------------------------------------------------------
# 4. CloudFront / UI
# ---------------------------------------------------------------
echo "--- CloudFront UI ---"
UI_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$UI_URL" 2>/dev/null || echo "000")
if [[ "$UI_STATUS" == "200" ]]; then
  pass "GET $UI_URL → $UI_STATUS"
else
  fail "GET $UI_URL → $UI_STATUS (expected 200)"
fi
echo ""

# ---------------------------------------------------------------
# 5. AgentCore Runtimes
# ---------------------------------------------------------------
echo "--- AgentCore Runtimes ---"
RUNTIMES=$(aws cloudformation describe-stack-resources \
  --stack-name aiops-cat-demo-agents --region "$REGION" \
  --query "StackResources[?ResourceType=='AWS::BedrockAgentCore::Runtime'].LogicalResourceId" \
  --output text 2>/dev/null || echo "")

if echo "$RUNTIMES" | grep -q "LangGraphRuntime"; then
  pass "LangGraphRuntime exists"
else
  fail "LangGraphRuntime NOT found"
fi

if echo "$RUNTIMES" | grep -q "StrandsRuntime"; then
  pass "StrandsRuntime exists"
else
  fail "StrandsRuntime NOT found"
fi
echo ""

# ---------------------------------------------------------------
# Summary
# ---------------------------------------------------------------
echo "============================================"
if [[ $FAILURES -eq 0 ]]; then
  printf "  \033[1;32mAll checks passed!\033[0m\n"
else
  printf "  \033[1;31m%d check(s) failed\033[0m\n" "$FAILURES"
fi
echo "============================================"
exit $FAILURES
