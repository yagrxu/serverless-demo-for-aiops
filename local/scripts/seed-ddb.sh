#!/usr/bin/env bash
# Seed health metrics and alerts directly into DynamoDB Local.
# These tables have no POST API endpoints, so we write via aws cli.
#
# Usage:
#   DDB_ENDPOINT=http://localhost:8001 ./local/scripts/seed-ddb.sh

set -euo pipefail

ENDPOINT="${DDB_ENDPOINT:-http://localhost:8001}"
REGION="${AWS_REGION:-us-east-1}"

export AWS_ACCESS_KEY_ID=local
export AWS_SECRET_ACCESS_KEY=local
export AWS_DEFAULT_REGION="$REGION"

ddb() { aws dynamodb --endpoint-url "$ENDPOINT" "$@"; }

put() {
  local table="$1" item="$2"
  ddb put-item --table-name "$table" --item "$item" >/dev/null
  printf "   put %s\n" "$table"
}

echo ">> seeding health data via DynamoDB at $ENDPOINT"

# =========================================================================
# Health Metrics — 火锅/hotpot (5 days)
# =========================================================================
echo ""
echo "--- health metrics: hotpot ---"

put HealthMetrics '{"cat_id":{"S":"hotpot"},"ts":{"S":"2026-04-28T09:00:00Z"},"weight_kg":{"N":"3.4"},"temp_c":{"N":"38.5"},"heart_rate":{"N":"140"},"activity":{"S":"high"},"water_intake_ml":{"N":"95"}}'
put HealthMetrics '{"cat_id":{"S":"hotpot"},"ts":{"S":"2026-04-29T09:00:00Z"},"weight_kg":{"N":"3.4"},"temp_c":{"N":"38.6"},"heart_rate":{"N":"135"},"activity":{"S":"medium"},"water_intake_ml":{"N":"80"}}'
put HealthMetrics '{"cat_id":{"S":"hotpot"},"ts":{"S":"2026-04-30T09:00:00Z"},"weight_kg":{"N":"3.5"},"temp_c":{"N":"38.4"},"heart_rate":{"N":"142"},"activity":{"S":"high"},"water_intake_ml":{"N":"90"}}'
put HealthMetrics '{"cat_id":{"S":"hotpot"},"ts":{"S":"2026-05-01T09:00:00Z"},"weight_kg":{"N":"3.5"},"temp_c":{"N":"38.5"},"heart_rate":{"N":"138"},"activity":{"S":"medium"},"water_intake_ml":{"N":"75"}}'
put HealthMetrics '{"cat_id":{"S":"hotpot"},"ts":{"S":"2026-05-02T09:00:00Z"},"weight_kg":{"N":"3.5"},"temp_c":{"N":"38.5"},"heart_rate":{"N":"140"},"activity":{"S":"low"},"water_intake_ml":{"N":"60"}}'

# =========================================================================
# Health Metrics — 烧烤/bbq (5 days)
# =========================================================================
echo ""
echo "--- health metrics: bbq ---"

put HealthMetrics '{"cat_id":{"S":"bbq"},"ts":{"S":"2026-04-28T09:00:00Z"},"weight_kg":{"N":"3.8"},"temp_c":{"N":"38.3"},"heart_rate":{"N":"150"},"activity":{"S":"medium"},"water_intake_ml":{"N":"110"}}'
put HealthMetrics '{"cat_id":{"S":"bbq"},"ts":{"S":"2026-04-29T09:00:00Z"},"weight_kg":{"N":"3.8"},"temp_c":{"N":"38.4"},"heart_rate":{"N":"148"},"activity":{"S":"medium"},"water_intake_ml":{"N":"105"}}'
put HealthMetrics '{"cat_id":{"S":"bbq"},"ts":{"S":"2026-04-30T09:00:00Z"},"weight_kg":{"N":"3.8"},"temp_c":{"N":"38.3"},"heart_rate":{"N":"145"},"activity":{"S":"high"},"water_intake_ml":{"N":"115"}}'
put HealthMetrics '{"cat_id":{"S":"bbq"},"ts":{"S":"2026-05-01T09:00:00Z"},"weight_kg":{"N":"3.9"},"temp_c":{"N":"38.4"},"heart_rate":{"N":"148"},"activity":{"S":"medium"},"water_intake_ml":{"N":"100"}}'
put HealthMetrics '{"cat_id":{"S":"bbq"},"ts":{"S":"2026-05-02T09:00:00Z"},"weight_kg":{"N":"3.9"},"temp_c":{"N":"38.3"},"heart_rate":{"N":"145"},"activity":{"S":"low"},"water_intake_ml":{"N":"85"}}'

# =========================================================================
# Health Alerts
# =========================================================================
echo ""
echo "--- health alerts ---"

put HealthAlerts '{"cat_id":{"S":"hotpot"},"alert_id":{"S":"alert-001"},"ts":{"S":"2026-05-02T10:00:00Z"},"type":{"S":"weight"},"severity":{"S":"warning"},"description":{"S":"锅锅体重达到 3.5kg（矮脚猫上限），建议控制饮食"},"status":{"S":"active"}}'
put HealthAlerts '{"cat_id":{"S":"hotpot"},"alert_id":{"S":"alert-002"},"ts":{"S":"2026-05-02T10:30:00Z"},"type":{"S":"hydration"},"severity":{"S":"warning"},"description":{"S":"锅锅今日饮水量仅 60ml，低于日均 85ml，建议检查饮水机"},"status":{"S":"active"}}'
put HealthAlerts '{"cat_id":{"S":"bbq"},"alert_id":{"S":"alert-003"},"ts":{"S":"2026-05-02T10:00:00Z"},"type":{"S":"weight"},"severity":{"S":"info"},"description":{"S":"烤烤体重微增至 3.9kg，仍在正常范围，持续观察"},"status":{"S":"active"}}'
put HealthAlerts '{"cat_id":{"S":"bbq"},"alert_id":{"S":"alert-004"},"ts":{"S":"2026-05-02T11:00:00Z"},"type":{"S":"litter"},"severity":{"S":"warning"},"description":{"S":"烤烤今日尚未使用猫砂盆（截至 11:00），上次使用超过 24 小时"},"status":{"S":"active"}}'
put HealthAlerts '{"cat_id":{"S":"fountain-1"},"alert_id":{"S":"alert-005"},"ts":{"S":"2026-05-02T08:30:00Z"},"type":{"S":"device"},"severity":{"S":"info"},"description":{"S":"饮水机水量连续 3 天下降（180→150→120ml），可能需要清洗或更换滤芯"},"status":{"S":"active"}}'

# =========================================================================
# Cat Name Index (reverse lookup: name/nickname → cat_id)
# =========================================================================
echo ""
echo "--- cat name index ---"

put CatNameIndex '{"name":{"S":"火锅"},"cat_id":{"S":"hotpot"},"name_type":{"S":"name"}}'
put CatNameIndex '{"name":{"S":"锅锅"},"cat_id":{"S":"hotpot"},"name_type":{"S":"nickname"}}'
put CatNameIndex '{"name":{"S":"烧烤"},"cat_id":{"S":"bbq"},"name_type":{"S":"name"}}'
put CatNameIndex '{"name":{"S":"烤烤"},"cat_id":{"S":"bbq"},"name_type":{"S":"nickname"}}'

echo ""
echo ">> done — seeded 10 health metrics + 5 health alerts + 4 name index entries"
