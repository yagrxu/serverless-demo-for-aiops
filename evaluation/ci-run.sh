#!/usr/bin/env bash
# CI evaluation script: starts the local stack, runs evaluation + judge.
#
# Prerequisites (handled by the GHA workflow):
#   - Python 3.12 with venvs for agents + mcp-server + evaluation
#   - Docker (for DynamoDB Local)
#   - AWS credentials configured (for Bedrock model calls)
#
# Usage:
#   ./evaluation/ci-run.sh [--threshold 0.7]
#
# Exit code: 0 if judge passes, 1 if regression detected.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
THRESHOLD="${1:-0.7}"

# Parse --threshold flag
for arg in "$@"; do
  case "$arg" in
    --threshold) shift; THRESHOLD="$1"; shift ;;
    --threshold=*) THRESHOLD="${arg#*=}" ;;
  esac
done

echo "============================================"
echo "  Agent Evaluation CI Run"
echo "  Threshold: $THRESHOLD"
echo "============================================"
echo ""

# ---------------------------------------------------------------------------
# Cleanup on exit
# ---------------------------------------------------------------------------
PIDS=()
cleanup() {
  echo ""
  echo ">> Cleaning up background processes..."
  for pid in "${PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  # Stop DynamoDB Local container
  docker rm -f eval-dynamodb 2>/dev/null || true
}
trap cleanup EXIT

# ---------------------------------------------------------------------------
# 1. Start DynamoDB Local
# ---------------------------------------------------------------------------
echo ">> Starting DynamoDB Local..."
docker run -d --name eval-dynamodb -p 8001:8000 amazon/dynamodb-local:latest >/dev/null
sleep 2

# ---------------------------------------------------------------------------
# 2. Seed DynamoDB
# ---------------------------------------------------------------------------
echo ">> Seeding DynamoDB..."
cd "$REPO_ROOT/local"
bash scripts/init-ddb.sh 2>/dev/null || true
bash scripts/seed-ddb.sh 2>/dev/null || true
cd "$REPO_ROOT"

# ---------------------------------------------------------------------------
# 3. Start API shim
# ---------------------------------------------------------------------------
echo ">> Starting API shim on :8000..."
cd "$REPO_ROOT/local/api"
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
  .venv/bin/pip install --quiet -r requirements.txt 2>/dev/null || true
fi
DYNAMODB_ENDPOINT=http://localhost:8001 \
  .venv/bin/python -m uvicorn app:app --host 0.0.0.0 --port 8000 &
PIDS+=($!)
cd "$REPO_ROOT"
sleep 2

# ---------------------------------------------------------------------------
# 4. Start MCP Server
# ---------------------------------------------------------------------------
echo ">> Starting MCP Server on :8083..."
cd "$REPO_ROOT/mcp-server"
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
  .venv/bin/pip install --quiet -r requirements.txt
fi
API_URL=http://localhost:8000 MCP_PORT=8083 \
  .venv/bin/python -m uvicorn server:mcp.app --host 0.0.0.0 --port 8083 &
PIDS+=($!)
cd "$REPO_ROOT"
sleep 2

# ---------------------------------------------------------------------------
# 5. Start agents
# ---------------------------------------------------------------------------
echo ">> Starting LangGraph agent on :8081..."
cd "$REPO_ROOT/agents/langgraph"
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
  .venv/bin/pip install --quiet -r requirements.txt
fi
MCP_SERVER_URL=http://localhost:8083/mcp \
  .venv/bin/python -m uvicorn server:app --host 0.0.0.0 --port 8081 &
PIDS+=($!)
cd "$REPO_ROOT"

echo ">> Starting Strands agent on :8082..."
cd "$REPO_ROOT/agents/strands"
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
  .venv/bin/pip install --quiet -r requirements.txt
fi
MCP_SERVER_URL=http://localhost:8083/mcp \
  .venv/bin/python -m uvicorn server:app --host 0.0.0.0 --port 8082 &
PIDS+=($!)
cd "$REPO_ROOT"

# ---------------------------------------------------------------------------
# 6. Wait for agents to be ready
# ---------------------------------------------------------------------------
echo ">> Waiting for agents to be ready..."
for port in 8081 8082; do
  for i in $(seq 1 30); do
    if curl -fsS -o /dev/null "http://localhost:$port/ping" 2>/dev/null; then
      echo "   :$port ready"
      break
    fi
    if [ "$i" -eq 30 ]; then
      echo "!! Agent on :$port failed to start after 30s"
      exit 1
    fi
    sleep 1
  done
done

# ---------------------------------------------------------------------------
# 7. Run evaluation
# ---------------------------------------------------------------------------
echo ""
echo ">> Running evaluation..."
cd "$REPO_ROOT/evaluation"
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
  .venv/bin/pip install --quiet -r requirements.txt
fi

RESULTS_FILE="results/ci-$(date +%Y%m%d-%H%M%S).json"
.venv/bin/python runner.py \
  --dataset datasets/comparative.yaml \
  --output "$RESULTS_FILE"

# ---------------------------------------------------------------------------
# 8. Run LLM-as-judge
# ---------------------------------------------------------------------------
echo ""
echo ">> Running LLM-as-judge..."
.venv/bin/python judge.py \
  "$RESULTS_FILE" \
  --threshold "$THRESHOLD" \
  --fail-on-regression

echo ""
echo ">> Evaluation complete!"
