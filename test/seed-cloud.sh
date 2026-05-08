#!/usr/bin/env bash
# Seed demo data into the cloud API (same data as local/scripts/seed.sh).
#
# Usage:
#   ./test/seed-cloud.sh
#   API_URL=https://xxx.execute-api.us-east-1.amazonaws.com/prod ./test/seed-cloud.sh

set -euo pipefail

API_URL="${API_URL:-https://thoctzvibl.execute-api.us-east-1.amazonaws.com/prod}"
REGION="${AWS_REGION:-us-east-1}"

post() {
  local code
  code=$(curl -sS -o /dev/null -w "%{http_code}" -X POST \
    -H 'Content-Type: application/json' -d "$2" "$API_URL$1")
  printf "   %s %s → %s\n" "POST" "$1" "$code"
}

echo ">> seeding cloud API at $API_URL"

# =========================================================================
# Cats
# =========================================================================
echo ""
echo "--- cats ---"

post /cats '{"cat_id":"hotpot","name":"火锅","nickname":"锅锅","gender":"male","breed":"英国短毛猫（矮脚）","color":"25色金渐层","body_type":"矮脚","birthday":"2023-04-27"}'
post /cats '{"cat_id":"bbq","name":"烧烤","nickname":"烤烤","gender":"female","breed":"英国短毛猫","color":"11色金渐层","body_type":"正常","birthday":"2023-06-14"}'

# =========================================================================
# Devices telemetry
# =========================================================================
echo ""
echo "--- devices ---"

post /devices/feeder-hotpot/telemetry '{"metrics":{"food_grams":420},"ts":"2026-05-02T07:15:00Z"}'
post /devices/feeder-bbq/telemetry    '{"metrics":{"food_grams":400},"ts":"2026-05-02T07:30:00Z"}'
post /devices/fountain-1/telemetry    '{"metrics":{"water_ml":120},"ts":"2026-05-02T08:00:00Z"}'
post /devices/litter-1/telemetry      '{"metrics":{"usage_count":2},"ts":"2026-05-02T10:00:00Z"}'

# =========================================================================
# Feedings — hotpot
# =========================================================================
echo ""
echo "--- feedings: hotpot ---"

post /feedings '{"cat_id":"hotpot","amount_grams":40,"food_type":"dry","ts":"2026-04-30T07:00:00Z"}'
post /feedings '{"cat_id":"hotpot","amount_grams":30,"food_type":"wet","ts":"2026-04-30T12:15:00Z"}'
post /feedings '{"cat_id":"hotpot","amount_grams":40,"food_type":"dry","ts":"2026-04-30T18:30:00Z"}'
post /feedings '{"cat_id":"hotpot","amount_grams":45,"food_type":"dry","ts":"2026-05-01T07:30:00Z"}'
post /feedings '{"cat_id":"hotpot","amount_grams":30,"food_type":"wet","ts":"2026-05-01T12:00:00Z"}'
post /feedings '{"cat_id":"hotpot","amount_grams":40,"food_type":"dry","ts":"2026-05-01T18:15:00Z"}'
post /feedings '{"cat_id":"hotpot","amount_grams":40,"food_type":"dry","ts":"2026-05-02T07:15:00Z"}'

# =========================================================================
# Feedings — bbq
# =========================================================================
echo ""
echo "--- feedings: bbq ---"

post /feedings '{"cat_id":"bbq","amount_grams":30,"food_type":"dry","ts":"2026-04-30T07:30:00Z"}'
post /feedings '{"cat_id":"bbq","amount_grams":30,"food_type":"wet","ts":"2026-04-30T18:00:00Z"}'
post /feedings '{"cat_id":"bbq","amount_grams":35,"food_type":"dry","ts":"2026-05-01T07:15:00Z"}'
post /feedings '{"cat_id":"bbq","amount_grams":30,"food_type":"wet","ts":"2026-05-01T18:30:00Z"}'
post /feedings '{"cat_id":"bbq","amount_grams":35,"food_type":"dry","ts":"2026-05-02T07:30:00Z"}'

echo ""
echo ">> done — seeded 2 cats, 4 devices, 12 feedings"
echo ""
echo "NOTE: Health metrics and alerts need direct DynamoDB writes."
echo "      Run: ./test/seed-cloud-ddb.sh"
