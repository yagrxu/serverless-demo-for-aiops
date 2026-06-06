# Setup Guide: Slack Integration for AIOps Cat Demo

This guide walks through the pre-deployment configuration needed for both integration paths:
- **Path A:** CloudWatch Alarm → SNS → Webhook Lambda → DevOps Agent (automated)
- **Path B:** Slack User → API Gateway → Slack Handler Lambda → DevOps Agent API (interactive)

---

## 1. Create a DevOps Agent Space

1. Open the **AWS DevOps Agent** console in `us-east-1`.
2. Click **Create Space**.
3. Name the space (e.g. `aiops-cat-demo-space`).
4. Under **Data Sources**, add:
   - **CloudWatch Logs** — select the log groups for your application (e.g. `/aws/lambda/aiops-cat-demo-*`, `/ecs/aiops-cat-demo`)
   - **CloudWatch Metrics** — select the namespace `AIOps/CatDemo` (or relevant custom metrics)
5. Under **Notification Channels**, add a **Slack** channel:
   - Connect your Slack workspace (OAuth flow)
   - Select the target channel where DevOps Agent will post investigation results
6. Save the Space. Note the **Space ID** (you'll need it later).

---

## 2. Obtain Webhook URL and HMAC Credentials

1. In the DevOps Agent console, open your Space.
2. Navigate to **Capabilities → Webhooks**.
3. Click **Generate** to create a new webhook endpoint.
4. Copy:
   - **Webhook URL** — the HTTPS endpoint to POST incident payloads to
   - **HMAC Secret** — used to sign outbound requests

Keep these values — they go into Secrets Manager in Step 4.

---

## 3. Create a Custom Slack App

### 3.1 Create the App

1. Go to [https://api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → **From scratch**.
2. Name it (e.g. `AIOps DevOps Bot`) and select your workspace.

### 3.2 Configure Bot Token Scopes

Navigate to **OAuth & Permissions** → **Scopes** → **Bot Token Scopes** and add:

| Scope | Purpose |
|-------|---------|
| `chat:write` | Post messages to channels |
| `commands` | Register slash commands |
| `app_mentions:read` | Receive `@bot` mentions |

### 3.3 Enable Event Subscriptions

1. Navigate to **Event Subscriptions** → toggle **Enable Events**.
2. Set the **Request URL** to your API Gateway endpoint (deploy CDK first, then come back):
   ```
   https://<api-id>.execute-api.us-east-1.amazonaws.com/slack/events
   ```
3. Under **Subscribe to bot events**, add:
   - `app_mention`

### 3.4 Create Slash Command

1. Navigate to **Slash Commands** → **Create New Command**.
2. Configure:
   - Command: `/devops`
   - Request URL: `https://<api-id>.execute-api.us-east-1.amazonaws.com/slack/events`
   - Short Description: `Ask DevOps Agent a question`

### 3.5 Install the App

1. Navigate to **Install App** → **Install to Workspace**.
2. Copy:
   - **Bot User OAuth Token** (`xoxb-...`)
   - **Signing Secret** (from **Basic Information** → **App Credentials**)

---

## 4. Store Secrets in Secrets Manager

Create two secrets in `us-east-1` with the exact names and JSON structures below.

### Secret 1: DevOps Agent Webhook Credentials

```bash
aws secretsmanager create-secret \
  --name "aiops-cat-demo/devops-agent-webhook" \
  --secret-string '{"webhook_url": "https://YOUR_WEBHOOK_URL", "hmac_secret": "YOUR_HMAC_SECRET"}' \
  --region us-east-1 \
  --profile cloudops-demo
```

**Expected JSON structure:**
```json
{
  "webhook_url": "https://...",
  "hmac_secret": "..."
}
```

### Secret 2: Slack Bot Credentials

```bash
aws secretsmanager create-secret \
  --name "aiops-cat-demo/slack-bot" \
  --secret-string '{"bot_token": "xoxb-YOUR-TOKEN", "signing_secret": "YOUR_SIGNING_SECRET", "devops_agent_space_id": "YOUR_SPACE_ID"}' \
  --region us-east-1 \
  --profile cloudops-demo
```

**Expected JSON structure:**
```json
{
  "bot_token": "xoxb-...",
  "signing_secret": "...",
  "devops_agent_space_id": "..."
}
```

### Get Secret ARNs (needed for CDK deploy)

```bash
aws secretsmanager describe-secret \
  --secret-id "aiops-cat-demo/devops-agent-webhook" \
  --query 'ARN' --output text \
  --region us-east-1 --profile cloudops-demo

aws secretsmanager describe-secret \
  --secret-id "aiops-cat-demo/slack-bot" \
  --query 'ARN' --output text \
  --region us-east-1 --profile cloudops-demo
```

---

## 5. IAM Permissions Reference

The Slack Handler Lambda needs `bedrock-agentcore:InvokeAgent` to call the DevOps Agent API. The CDK stack attaches this automatically, scoped to your DevOps Agent Space ARN:

```json
{
  "Effect": "Allow",
  "Action": "bedrock-agentcore:InvokeAgent",
  "Resource": "arn:aws:bedrock-agentcore:us-east-1:<ACCOUNT_ID>:space/<SPACE_ID>"
}
```

Both Lambdas also get `secretsmanager:GetSecretValue` scoped to their respective secret ARNs. No additional IAM setup is required — the CDK stack handles this.

---

## 6. Deploy the CDK Stack

```bash
AWS_PROFILE=cloudops-demo npx cdk deploy aiops-cat-demo-slack \
  -c slackEnabled=true \
  -c imageTag=$(git rev-parse HEAD) \
  --region us-east-1
```

After deployment, note the **SlackApiEndpoint** output — use it to configure the Slack App Request URL (Step 3.3 and 3.4).

---

## 7. Verification

### Path A: Automated Alarm → DevOps Agent

1. Trigger a CloudWatch alarm (or set a metric alarm to `ALARM` state):
   ```bash
   aws cloudwatch set-alarm-state \
     --alarm-name "aiops-cat-demo-high-error-rate" \
     --state-value ALARM \
     --state-reason "Testing Slack integration" \
     --region us-east-1 --profile cloudops-demo
   ```
2. Check CloudWatch Logs for the Webhook Lambda:
   ```bash
   aws logs tail /aws/lambda/aiops-cat-demo-webhook-forwarder \
     --since 5m --follow \
     --region us-east-1 --profile cloudops-demo
   ```
3. Confirm the DevOps Agent posts investigation results to the configured Slack channel.

### Path B: Interactive Slack → DevOps Agent

1. In Slack, mention the bot:
   ```
   @AIOps DevOps Bot why is the feeding endpoint slow?
   ```
2. Or use the slash command:
   ```
   /devops investigate high latency on device API
   ```
3. Verify a response appears in the channel within ~60 seconds.
4. Check CloudWatch Logs for the Slack Handler Lambda:
   ```bash
   aws logs tail /aws/lambda/aiops-cat-demo-slack-handler \
     --since 5m --follow \
     --region us-east-1 --profile cloudops-demo
   ```

---

## 8. Troubleshooting

### Webhook Lambda not firing

- Confirm the SNS subscription exists:
  ```bash
  aws sns list-subscriptions-by-topic \
    --topic-arn arn:aws:sns:us-east-1:<ACCOUNT_ID>:aiops-cat-demo-alarms \
    --region us-east-1 --profile cloudops-demo
  ```
- Check the Lambda has permission to be invoked by SNS (CDK handles this automatically).

### HMAC signature rejected by DevOps Agent

- Ensure the `hmac_secret` in Secrets Manager matches what was generated in the DevOps Agent console.
- Check that JSON serialization uses sorted keys with no extra whitespace (`sort_keys=True, separators=(',', ':')`).

### Slack request signature verification failing (HTTP 401)

- Ensure `signing_secret` in Secrets Manager matches the value in Slack App → Basic Information → App Credentials.
- Verify the Slack App Request URL points to the correct API Gateway endpoint.
- Check that the clock on Lambda is in sync (timestamps older than 5 minutes are rejected).

### DevOps Agent API errors

- Verify the `devops_agent_space_id` in Secrets Manager is correct.
- Confirm the Lambda execution role has `bedrock-agentcore:InvokeAgent` permission:
  ```bash
  aws iam list-role-policies \
    --role-name <slack-handler-role-name> \
    --region us-east-1 --profile cloudops-demo
  ```
- Check if the DevOps Agent Space is active and has data sources configured.

### Slack bot not responding

- Ensure the bot is invited to the channel (`/invite @AIOps DevOps Bot`).
- Verify Event Subscriptions shows a green checkmark (Request URL verified).
- Check that `app_mention` is subscribed under bot events.
- Confirm the `bot_token` in Secrets Manager starts with `xoxb-` and has `chat:write` scope.

### Lambda timeout

- Webhook Lambda timeout (30s): Check network connectivity to DevOps Agent endpoint.
- Slack Handler timeout (60s): The DevOps Agent API has a 55s soft deadline. If investigations are complex, consider increasing the timeout or advising the user to retry.

### Secrets Manager access denied

- Ensure the Lambda execution role has `secretsmanager:GetSecretValue` scoped to the correct secret ARN.
- Verify the secret exists in `us-east-1` (not a different region).
