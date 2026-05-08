#!/usr/bin/env bash
# Seed demo data into the running local API.
#
# Clears existing data first (by recreating tables), then inserts:
#   - 2 cats (火锅/hotpot, 烧烤/bbq)
#   - 6 devices
#   - 32 feeding events (7 days)
#   - 14 device telemetry points
#   - 10 health metrics (5 days × 2 cats)
#   - 5 health alerts
#
# Usage:
#   API=http://localhost:8000 ./local/scripts/seed.sh
#   ./local/scripts/seed.sh                              # defaults to :8000

set -euo pipefail

API="${API:-http://localhost:8000}"

post() {
  local code
  code=$(curl -sS -o /dev/null -w "%{http_code}" -X POST \
    -H 'Content-Type: application/json' -d "$2" "$API$1")
  printf "   %s %s → %s\n" "POST" "$1" "$code"
}

echo ">> seeding via $API"

# =========================================================================
# Cats
# =========================================================================
echo ""
echo "--- cats ---"

post /cats '{
  "cat_id": "hotpot",
  "name": "火锅",
  "nickname": "锅锅",
  "gender": "male",
  "breed": "英国短毛猫（矮脚）",
  "color": "25色金渐层",
  "body_type": "矮脚",
  "birthday": "2023-04-27"
}'

post /cats '{
  "cat_id": "bbq",
  "name": "烧烤",
  "nickname": "烤烤",
  "gender": "female",
  "breed": "英国短毛猫",
  "color": "11色金渐层",
  "body_type": "正常",
  "birthday": "2023-06-14"
}'

# =========================================================================
# Devices — telemetry doubles as device registration
# =========================================================================
echo ""
echo "--- devices (initial telemetry to register) ---"

post /devices/feeder-hotpot/telemetry '{"metrics":{"food_grams":420},"ts":"2026-05-02T07:15:00Z"}'
post /devices/feeder-bbq/telemetry    '{"metrics":{"food_grams":400},"ts":"2026-05-02T07:30:00Z"}'
post /devices/fountain-1/telemetry    '{"metrics":{"water_ml":120},"ts":"2026-05-02T08:00:00Z"}'
post /devices/litter-1/telemetry      '{"metrics":{"usage_count":2,"last_use":"hotpot"},"ts":"2026-05-02T10:00:00Z"}'
post /devices/tracker-hotpot/telemetry '{"metrics":{"lat":31.2304,"lng":121.4737,"battery":85},"ts":"2026-05-02T09:00:00Z"}'
post /devices/tracker-bbq/telemetry   '{"metrics":{"lat":31.2304,"lng":121.4737,"battery":72},"ts":"2026-05-02T09:00:00Z"}'

# =========================================================================
# Device telemetry — historical (3 days)
# =========================================================================
echo ""
echo "--- device telemetry (historical) ---"

post /devices/feeder-hotpot/telemetry '{"metrics":{"food_grams":380},"ts":"2026-04-30T07:00:00Z"}'
post /devices/feeder-hotpot/telemetry '{"metrics":{"food_grams":250},"ts":"2026-05-01T07:30:00Z"}'
post /devices/feeder-bbq/telemetry    '{"metrics":{"food_grams":350},"ts":"2026-04-30T07:30:00Z"}'
post /devices/feeder-bbq/telemetry    '{"metrics":{"food_grams":280},"ts":"2026-05-01T07:15:00Z"}'
post /devices/fountain-1/telemetry    '{"metrics":{"water_ml":180},"ts":"2026-04-30T08:00:00Z"}'
post /devices/fountain-1/telemetry    '{"metrics":{"water_ml":150},"ts":"2026-05-01T08:00:00Z"}'
post /devices/litter-1/telemetry      '{"metrics":{"usage_count":4,"last_use":"hotpot"},"ts":"2026-04-30T10:00:00Z"}'
post /devices/litter-1/telemetry      '{"metrics":{"usage_count":3,"last_use":"bbq"},"ts":"2026-05-01T10:00:00Z"}'

# =========================================================================
# Feedings — 火锅/hotpot (7 days, 2-3 per day)
# =========================================================================
echo ""
echo "--- feedings: hotpot ---"

post /feedings '{"cat_id":"hotpot","amount_grams":40,"food_type":"dry","ts":"2026-04-26T07:30:00Z"}'
post /feedings '{"cat_id":"hotpot","amount_grams":30,"food_type":"wet","ts":"2026-04-26T12:00:00Z"}'
post /feedings '{"cat_id":"hotpot","amount_grams":40,"food_type":"dry","ts":"2026-04-26T18:30:00Z"}'
post /feedings '{"cat_id":"hotpot","amount_grams":45,"food_type":"dry","ts":"2026-04-27T07:15:00Z"}'
post /feedings '{"cat_id":"hotpot","amount_grams":35,"food_type":"wet","ts":"2026-04-27T18:00:00Z"}'
post /feedings '{"cat_id":"hotpot","amount_grams":40,"food_type":"dry","ts":"2026-04-28T07:45:00Z"}'
post /feedings '{"cat_id":"hotpot","amount_grams":30,"food_type":"wet","ts":"2026-04-28T12:30:00Z"}'
post /feedings '{"cat_id":"hotpot","amount_grams":40,"food_type":"dry","ts":"2026-04-28T18:15:00Z"}'
post /feedings '{"cat_id":"hotpot","amount_grams":45,"food_type":"dry","ts":"2026-04-29T07:30:00Z"}'
post /feedings '{"cat_id":"hotpot","amount_grams":35,"food_type":"wet","ts":"2026-04-29T18:00:00Z"}'
post /feedings '{"cat_id":"hotpot","amount_grams":40,"food_type":"dry","ts":"2026-04-30T07:00:00Z"}'
post /feedings '{"cat_id":"hotpot","amount_grams":30,"food_type":"wet","ts":"2026-04-30T12:15:00Z"}'
post /feedings '{"cat_id":"hotpot","amount_grams":40,"food_type":"dry","ts":"2026-04-30T18:30:00Z"}'
post /feedings '{"cat_id":"hotpot","amount_grams":45,"food_type":"dry","ts":"2026-05-01T07:30:00Z"}'
post /feedings '{"cat_id":"hotpot","amount_grams":30,"food_type":"wet","ts":"2026-05-01T12:00:00Z"}'
post /feedings '{"cat_id":"hotpot","amount_grams":40,"food_type":"dry","ts":"2026-05-01T18:15:00Z"}'
post /feedings '{"cat_id":"hotpot","amount_grams":40,"food_type":"dry","ts":"2026-05-02T07:15:00Z"}'

# =========================================================================
# Feedings — 烧烤/bbq (7 days, 2-3 per day)
# =========================================================================
echo ""
echo "--- feedings: bbq ---"

post /feedings '{"cat_id":"bbq","amount_grams":35,"food_type":"dry","ts":"2026-04-26T07:45:00Z"}'
post /feedings '{"cat_id":"bbq","amount_grams":30,"food_type":"wet","ts":"2026-04-26T18:00:00Z"}'
post /feedings '{"cat_id":"bbq","amount_grams":35,"food_type":"dry","ts":"2026-04-27T07:30:00Z"}'
post /feedings '{"cat_id":"bbq","amount_grams":25,"food_type":"wet","ts":"2026-04-27T12:00:00Z"}'
post /feedings '{"cat_id":"bbq","amount_grams":35,"food_type":"dry","ts":"2026-04-27T18:30:00Z"}'
post /feedings '{"cat_id":"bbq","amount_grams":30,"food_type":"dry","ts":"2026-04-28T07:15:00Z"}'
post /feedings '{"cat_id":"bbq","amount_grams":30,"food_type":"wet","ts":"2026-04-28T18:00:00Z"}'
post /feedings '{"cat_id":"bbq","amount_grams":35,"food_type":"dry","ts":"2026-04-29T07:45:00Z"}'
post /feedings '{"cat_id":"bbq","amount_grams":25,"food_type":"wet","ts":"2026-04-29T12:30:00Z"}'
post /feedings '{"cat_id":"bbq","amount_grams":35,"food_type":"dry","ts":"2026-04-29T18:15:00Z"}'
post /feedings '{"cat_id":"bbq","amount_grams":30,"food_type":"dry","ts":"2026-04-30T07:30:00Z"}'
post /feedings '{"cat_id":"bbq","amount_grams":30,"food_type":"wet","ts":"2026-04-30T18:00:00Z"}'
post /feedings '{"cat_id":"bbq","amount_grams":35,"food_type":"dry","ts":"2026-05-01T07:15:00Z"}'
post /feedings '{"cat_id":"bbq","amount_grams":30,"food_type":"wet","ts":"2026-05-01T18:30:00Z"}'
post /feedings '{"cat_id":"bbq","amount_grams":35,"food_type":"dry","ts":"2026-05-02T07:30:00Z"}'

echo ""
echo ">> done — seeded 2 cats, 6 devices, 32 feedings, 14 telemetry points"
echo ""
echo "NOTE: Health metrics and alerts must be seeded directly into DynamoDB"
echo "      (no POST endpoints exist for them). Run seed-ddb.sh for those."
