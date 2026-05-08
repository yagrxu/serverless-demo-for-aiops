#!/usr/bin/env bash
# Seed health metrics and alerts directly into cloud DynamoDB.
# CDK-generated table names include the stack prefix — this script
# discovers them automatically.
#
# Usage:
#   ./test/seed-cloud-ddb.sh

set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"

# Discover CDK-generated table names
find_table() {
  aws dynamodb list-tables --region "$REGION" --query "TableNames" --output text | tr '\t' '\n' | grep "$1" | head -1
}

HEALTH_METRICS_TABLE=$(find_table "HealthMetrics")
HEALTH_ALERTS_TABLE=$(find_table "HealthAlerts")
CAT_NAME_INDEX_TABLE=$(find_table "CatNameIndex")

echo ">> Discovered tables:"
echo "   HealthMetrics: $HEALTH_METRICS_TABLE"
echo "   HealthAlerts:  $HEALTH_ALERTS_TABLE"
echo "   CatNameIndex:  $CAT_NAME_INDEX_TABLE"
echo ""

ddb() { aws dynamodb --region "$REGION" "$@"; }

put() {
  local table="$1" item="$2"
  ddb put-item --table-name "$table" --item "$item" >/dev/null
  printf "   put %s\n" "$table"
}

# =========================================================================
# Cat Name Index
# =========================================================================
echo "--- cat name index ---"

put "$CAT_NAME_INDEX_TABLE" '{"name":{"S":"火锅"},"cat_id":{"S":"hotpot"},"name_type":{"S":"name"}}'
put "$CAT_NAME_INDEX_TABLE" '{"name":{"S":"锅锅"},"cat_id":{"S":"hotpot"},"name_type":{"S":"nickname"}}'
put "$CAT_NAME_INDEX_TABLE" '{"name":{"S":"烧烤"},"cat_id":{"S":"bbq"},"name_type":{"S":"name"}}'
put "$CAT_NAME_INDEX_TABLE" '{"name":{"S":"烤烤"},"cat_id":{"S":"bbq"},"name_type":{"S":"nickname"}}'

# =========================================================================
# Health Metrics — hotpot
# =========================================================================
echo ""
echo "--- health metrics: hotpot ---"

put "$HEALTH_METRICS_TABLE" '{"cat_id":{"S":"hotpot"},"ts":{"S":"2026-04-28T09:00:00Z"},"weight_kg":{"N":"3.4"},"temp_c":{"N":"38.5"},"heart_rate":{"N":"140"},"activity":{"S":"high"},"water_intake_ml":{"N":"95"}}'
put "$HEALTH_METRICS_TABLE" '{"cat_id":{"S":"hotpot"},"ts":{"S":"2026-04-29T09:00:00Z"},"weight_kg":{"N":"3.4"},"temp_c":{"N":"38.6"},"heart_rate":{"N":"135"},"activity":{"S":"medium"},"water_intake_ml":{"N":"80"}}'
put "$HEALTH_METRICS_TABLE" '{"cat_id":{"S":"hotpot"},"ts":{"S":"2026-04-30T09:00:00Z"},"weight_kg":{"N":"3.5"},"temp_c":{"N":"38.4"},"heart_rate":{"N":"142"},"activity":{"S":"high"},"water_intake_ml":{"N":"90"}}'
put "$HEALTH_METRICS_TABLE" '{"cat_id":{"S":"hotpot"},"ts":{"S":"2026-05-01T09:00:00Z"},"weight_kg":{"N":"3.5"},"temp_c":{"N":"38.5"},"heart_rate":{"N":"138"},"activity":{"S":"medium"},"water_intake_ml":{"N":"75"}}'
put "$HEALTH_METRICS_TABLE" '{"cat_id":{"S":"hotpot"},"ts":{"S":"2026-05-02T09:00:00Z"},"weight_kg":{"N":"3.5"},"temp_c":{"N":"38.5"},"heart_rate":{"N":"140"},"activity":{"S":"low"},"water_intake_ml":{"N":"60"}}'

# =========================================================================
# Health Metrics — bbq
# =========================================================================
echo ""
echo "--- health metrics: bbq ---"

put "$HEALTH_METRICS_TABLE" '{"cat_id":{"S":"bbq"},"ts":{"S":"2026-04-28T09:00:00Z"},"weight_kg":{"N":"3.8"},"temp_c":{"N":"38.3"},"heart_rate":{"N":"150"},"activity":{"S":"medium"},"water_intake_ml":{"N":"110"}}'
put "$HEALTH_METRICS_TABLE" '{"cat_id":{"S":"bbq"},"ts":{"S":"2026-04-29T09:00:00Z"},"weight_kg":{"N":"3.8"},"temp_c":{"N":"38.4"},"heart_rate":{"N":"148"},"activity":{"S":"medium"},"water_intake_ml":{"N":"105"}}'
put "$HEALTH_METRICS_TABLE" '{"cat_id":{"S":"bbq"},"ts":{"S":"2026-04-30T09:00:00Z"},"weight_kg":{"N":"3.8"},"temp_c":{"N":"38.3"},"heart_rate":{"N":"145"},"activity":{"S":"high"},"water_intake_ml":{"N":"115"}}'
put "$HEALTH_METRICS_TABLE" '{"cat_id":{"S":"bbq"},"ts":{"S":"2026-05-01T09:00:00Z"},"weight_kg":{"N":"3.9"},"temp_c":{"N":"38.4"},"heart_rate":{"N":"148"},"activity":{"S":"medium"},"water_intake_ml":{"N":"100"}}'
put "$HEALTH_METRICS_TABLE" '{"cat_id":{"S":"bbq"},"ts":{"S":"2026-05-02T09:00:00Z"},"weight_kg":{"N":"3.9"},"temp_c":{"N":"38.3"},"heart_rate":{"N":"145"},"activity":{"S":"low"},"water_intake_ml":{"N":"85"}}'

# =========================================================================
# Health Alerts
# =========================================================================
echo ""
echo "--- health alerts ---"

put "$HEALTH_ALERTS_TABLE" '{"cat_id":{"S":"hotpot"},"alert_id":{"S":"alert-001"},"ts":{"S":"2026-05-02T10:00:00Z"},"type":{"S":"weight"},"severity":{"S":"warning"},"description":{"S":"锅锅体重达到 3.5kg（矮脚猫上限），建议控制饮食"},"status":{"S":"active"}}'
put "$HEALTH_ALERTS_TABLE" '{"cat_id":{"S":"hotpot"},"alert_id":{"S":"alert-002"},"ts":{"S":"2026-05-02T10:30:00Z"},"type":{"S":"hydration"},"severity":{"S":"warning"},"description":{"S":"锅锅今日饮水量仅 60ml，低于日均 85ml，建议检查饮水机"},"status":{"S":"active"}}'
put "$HEALTH_ALERTS_TABLE" '{"cat_id":{"S":"bbq"},"alert_id":{"S":"alert-003"},"ts":{"S":"2026-05-02T10:00:00Z"},"type":{"S":"weight"},"severity":{"S":"info"},"description":{"S":"烤烤体重微增至 3.9kg，仍在正常范围，持续观察"},"status":{"S":"active"}}'
put "$HEALTH_ALERTS_TABLE" '{"cat_id":{"S":"bbq"},"alert_id":{"S":"alert-004"},"ts":{"S":"2026-05-02T11:00:00Z"},"type":{"S":"litter"},"severity":{"S":"warning"},"description":{"S":"烤烤今日尚未使用猫砂盆（截至 11:00），上次使用超过 24 小时"},"status":{"S":"active"}}'
put "$HEALTH_ALERTS_TABLE" '{"cat_id":{"S":"fountain-1"},"alert_id":{"S":"alert-005"},"ts":{"S":"2026-05-02T08:30:00Z"},"type":{"S":"device"},"severity":{"S":"info"},"description":{"S":"饮水机水量连续 3 天下降（180→150→120ml），可能需要清洗或更换滤芯"},"status":{"S":"active"}}'

echo ""
echo ">> done — seeded 10 health metrics + 5 alerts + 4 name index entries"
