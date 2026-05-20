# AIOps Investigation Demo Script

**Duration:** 10–15 minutes  
**Audience:** Developers, SREs, AIOps practitioners  
**Goal:** Show that every injected bug surfaces as a CloudWatch signal without manual log grepping.

---

## Prerequisites

- AWS account with profile `cloudops-demo` (test account, `us-east-1`)
- All stacks deployed: `cdk deploy --all --profile cloudops-demo`
- SNS alarm subscription confirmed (check email)
- Anomaly detectors have ≥14 days of baseline data (or silence alarms during warm-up)
- Transaction Search enabled (verify: `aws xray get-trace-segment-destination --region us-east-1`)

---

## Step 1 — Verify the stack is healthy

```bash
# Confirm all stacks are CREATE_COMPLETE / UPDATE_COMPLETE
aws cloudformation list-stacks \
  --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE \
  --query "StackSummaries[?starts_with(StackName,'aiops-cat-demo')].StackName" \
  --region us-east-1 --profile cloudops-demo

# Quick smoke test — hit each Lambda via API Gateway
API_URL=$(aws cloudformation describe-stacks \
  --stack-name aiops-cat-demo-api \
  --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" \
  --output text --region us-east-1 --profile cloudops-demo)

curl -s "$API_URL/cats" | jq .
curl -s "$API_URL/devices" | jq .
curl -s "$API_URL/feedings" | jq .
curl -s "$API_URL/health/metrics" | jq .
```

**Check dashboards are rendering:**

- SRE Dashboard: https://us-east-1.console.aws.amazon.com/cloudwatch/home?region=us-east-1#dashboards/dashboard/aiops-cat-demo-sre
- GenAI Dashboard: https://us-east-1.console.aws.amazon.com/cloudwatch/home?region=us-east-1#dashboards/dashboard/aiops-cat-demo-genai
- Business Dashboard: https://us-east-1.console.aws.amazon.com/cloudwatch/home?region=us-east-1#dashboards/dashboard/aiops-cat-demo-business

All alarm widgets should show **OK** (green).

---

## Step 2 — Inject a bug

Pick one scenario from the table below. For a live demo, **Scenario 1 (feeding memory leak)** or **Scenario 3 (device silent error)** work best because they fire alarms within minutes.

```bash
# Example: inject Scenario 1 — feeding Lambda memory leak
git checkout -b feature/demo-bug-feeding-leak main
# Edit cdk/lambda/feeding/handler.py to introduce the leak (see bug-scenarios.md)
git add -A && git commit -m "inject: feeding memory leak for demo"
git push --no-verify --force-with-lease origin feature/demo-bug-feeding-leak:test
```

Wait for the GitHub Actions deploy workflow to complete (~3 minutes).

---

## Step 3 — Generate traffic

Use the chatbot UI or direct API calls to trigger the buggy code path repeatedly.

```bash
# Direct traffic to the feeding endpoint (Scenario 1)
for i in $(seq 1 50); do
  curl -s -X POST "$API_URL/feedings" \
    -H "Content-Type: application/json" \
    -d '{"cat_id":"cat-001","food_type":"wet","amount_grams":100}' &
done
wait

# Or open the Chatbot UI and ask: "Feed cat-001 wet food 100g" repeatedly
```

For agent-layer scenarios (5, 6), use the chatbot UI to send prompts that exercise the buggy agent path.

---

## Step 4 — Observe signals

### 4a. Application Signals Service Map

**URL:** https://us-east-1.console.aws.amazon.com/cloudwatch/home?region=us-east-1#application-signals:services

- Shows the affected Lambda with a red/yellow edge to DynamoDB
- Click the node → see latency and error rate spike

### 4b. SRE Dashboard

**URL:** https://us-east-1.console.aws.amazon.com/cloudwatch/home?region=us-east-1#dashboards/dashboard/aiops-cat-demo-sre

- Row 1: `AlarmStatusWidget` — the affected alarm turns red
- Row 3: Lambda Duration p50/p90/p99 — spike visible on the injected function
- Row 4: Lambda Errors — count > 0 for the affected function
- Row 7–8: Contributor Insights — hot partition visible (Scenarios 2, 10)

### 4c. Alarm fires → SNS notification

**URL:** https://us-east-1.console.aws.amazon.com/cloudwatch/home?region=us-east-1#alarmsV2:

- Filter by state `In alarm`
- The alarm name matches the scenario (e.g., `aiops-cat-demo-feeding-duration-p99-anomaly`)
- Check email for the SNS notification

### 4d. Contributor Insights (Scenarios 2, 10)

**URL:** https://us-east-1.console.aws.amazon.com/cloudwatch/home?region=us-east-1#contributor-insights:rules

- `DeviceTelemetry` rule shows the hot `cat_id` partition key
- `HealthMetrics` rule shows the scanned partition

### 4e. Business Dashboard (Scenario 3)

**URL:** https://us-east-1.console.aws.amazon.com/cloudwatch/home?region=us-east-1#dashboards/dashboard/aiops-cat-demo-business

- `DeviceWriteSuccess` sparkline drops to zero while `DevicesCommanded` stays steady
- The anomaly band alarm fires

### 4f. GenAI Dashboard (Scenarios 5, 6)

**URL:** https://us-east-1.console.aws.amazon.com/cloudwatch/home?region=us-east-1#dashboards/dashboard/aiops-cat-demo-genai

- Token usage spikes for the affected runtime
- LangGraph vs Strands comparison widget shows divergence
- Slowest tool calls log query widget shows the looping calls

---

## Step 5 — Investigate

### 5a. CloudWatch Logs Insights — structured log query

**URL:** https://us-east-1.console.aws.amazon.com/cloudwatch/home?region=us-east-1#logsV2:logs-insights

Use saved query **"A — All errors for a trace"**:

```
fields @timestamp, @log, @message, level
| filter xray_trace_id = '<paste-trace-id-from-alarm>'
| filter level in ['ERROR','WARN']
| sort @timestamp asc
```

Pick the trace ID from the alarm details or from the Service Map's failing request.

### 5b. Transaction Search — trace drill-down

**URL:** https://us-east-1.console.aws.amazon.com/cloudwatch/home?region=us-east-1#xray:traces

- Filter by service name or status code
- Click a failing trace → waterfall view shows exactly which DynamoDB call failed or which Lambda timed out
- For agent scenarios: filter by `session.id` to see the full conversation trace

### 5c. GenAI Observability console (Scenarios 5, 6)

**URL:** https://us-east-1.console.aws.amazon.com/cloudwatch/home?region=us-east-1#generative-ai:observability

- Select the affected runtime
- View session list → click the suspect session
- Trace waterfall shows repeated tool calls (infinite loop) or wrong tool selection

---

## Step 6 — Resolve

```bash
# Identify root cause from traces + metrics (done in Step 5)
# Fix the code on the feature branch
git checkout feature/demo-bug-feeding-leak
# Revert the injected bug
git revert HEAD
git push --no-verify origin feature/demo-bug-feeding-leak:test
```

Wait for deploy (~3 minutes), then verify recovery:

```bash
# Generate normal traffic
for i in $(seq 1 20); do
  curl -s -X POST "$API_URL/feedings" \
    -H "Content-Type: application/json" \
    -d '{"cat_id":"cat-001","food_type":"dry","amount_grams":50}' &
done
wait
```

**Verify:**
- SRE Dashboard alarm widget returns to green (OK)
- Duration p99 returns to baseline
- Business metrics resume normal rate

---

## Per-Scenario Quick Reference

| # | Scenario | Inject | Traffic | Signal fires within | Proof URL |
|---|----------|--------|---------|---------------------|-----------|
| 1 | Feeding memory leak / OOM | Edit `cdk/lambda/feeding/handler.py` — allocate growing list per invocation | `POST /feedings` × 50 | 5 min | [SRE Dashboard — Duration + Errors](https://us-east-1.console.aws.amazon.com/cloudwatch/home?region=us-east-1#dashboards/dashboard/aiops-cat-demo-sre) |
| 2 | Health full-table scan | Edit `cdk/lambda/health/handler.py` — replace `query()` with `scan()` | `GET /health/metrics?cat_id=cat-001` × 30 | 10 min | [Contributor Insights](https://us-east-1.console.aws.amazon.com/cloudwatch/home?region=us-east-1#contributor-insights:rules) |
| 3 | Device silent DDB error | Edit `cdk/lambda/device/handler.py` — catch `ClientError`, return `[]` | `POST /devices/{id}/telemetry` × 50 | 15 min | [Business Dashboard — DeviceWriteSuccess](https://us-east-1.console.aws.amazon.com/cloudwatch/home?region=us-east-1#dashboards/dashboard/aiops-cat-demo-business) |
| 4 | Stale cat-profile cache | Edit `cdk/lambda/cat-profile/handler.py` — skip cache invalidation on PUT | `PUT /cats/{id}` then `GET /cats/{id}` via chatbot | Visual | [Transaction Search — session trace](https://us-east-1.console.aws.amazon.com/cloudwatch/home?region=us-east-1#xray:traces) |
| 5 | LangGraph infinite loop | Edit `agents/langgraph/server.py` — remove loop guard | Chatbot prompt: "What should I feed cat-001?" | 2 min | [GenAI Dashboard — token anomaly](https://us-east-1.console.aws.amazon.com/cloudwatch/home?region=us-east-1#dashboards/dashboard/aiops-cat-demo-genai) |
| 6 | Strands wrong tool | Edit `agents/strands/server.py` — reorder tool priority | Chatbot prompt: "Show health for cat-001" | Visual | [GenAI Dashboard — LangGraph vs Strands](https://us-east-1.console.aws.amazon.com/cloudwatch/home?region=us-east-1#dashboards/dashboard/aiops-cat-demo-genai) |
| 7 | Gateway target misconfigured | Redeploy with wrong target ARN in agent config | Any chatbot prompt | 1 min | [Alarms — Gateway target errors](https://us-east-1.console.aws.amazon.com/cloudwatch/home?region=us-east-1#alarmsV2:) |
| 8 | Bedrock throttle | Drive burst: 20 concurrent chatbot prompts | Chatbot burst | 1 min | [Alarms — Bedrock throttle](https://us-east-1.console.aws.amazon.com/cloudwatch/home?region=us-east-1#alarmsV2:) |
| 9 | Chatbot retry storm | Force 5xx from runtime; chatbot retries infinitely | Open chatbot UI, send any prompt | 5 min | [Alarms — RUM error rate + CF 5xx](https://us-east-1.console.aws.amazon.com/cloudwatch/home?region=us-east-1#alarmsV2:) |
| 10 | DDB hot partition | Edit `cdk/lambda/device/handler.py` — hardcode `cat_id=cat-001` for all writes | `POST /devices/{id}/telemetry` × 100 | 10 min | [Contributor Insights — DeviceTelemetry top key](https://us-east-1.console.aws.amazon.com/cloudwatch/home?region=us-east-1#contributor-insights:rules) |

---

## Tips for a smooth demo

- **Pre-warm anomaly detectors.** They need ~14 days of data. Deploy the stack to the test account well before the demo.
- **Use Scenario 1 or 3 for time-constrained demos.** They fire alarms quickly and the signal is unambiguous.
- **Keep a terminal with `aws cloudwatch describe-alarms --state-value ALARM`** running to show the alarm transition live.
- **Open dashboards in separate browser tabs** before starting so you can switch instantly.
- **Transaction Search has a ~10-minute lag on first enable.** Verify it's populated before the demo.
- **Clean up after:** revert the bug branch and force-push `main:test` to restore healthy state.

```bash
# Restore healthy state
git push --no-verify --force-with-lease origin main:test
```
