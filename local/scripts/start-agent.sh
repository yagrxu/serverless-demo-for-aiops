#!/usr/bin/env bash
# Start a single agent on the host.
#
#   ./local/scripts/start-agent.sh langgraph   # start LangGraph on :8081
#   ./local/scripts/start-agent.sh strands     # start Strands on :8082
#
# Assumes Docker + MCP Server are already running (use up.sh --no-agents first).
# The agent runs in the foreground so you can see logs directly and Ctrl-C to stop.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

usage() {
  echo "Usage: $0 <langgraph|strands>"
  exit 1
}

[[ $# -lt 1 ]] && usage

AGENT="$1"
case "$AGENT" in
  langgraph) PORT=8081 ;;
  strands)   PORT=8082 ;;
  *) echo "Unknown agent: $AGENT (choose langgraph or strands)"; exit 1 ;;
esac

AGENT_DIR="$REPO_ROOT/agents/$AGENT"
VENV="$AGENT_DIR/.venv"

# Create venv if needed
if [[ ! -d "$VENV" ]]; then
  echo ">> creating venv for $AGENT"
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install --quiet -r "$AGENT_DIR/requirements.txt"
fi

# Quick sanity check: is MCP Server up?
if ! curl -fsS -o /dev/null http://localhost:8083/health 2>/dev/null; then
  echo "!! MCP Server not responding on :8083 — start it first (./local/scripts/up.sh --no-agents)"
  echo "   Continuing anyway, agent will retry connection..."
fi

echo ">> starting $AGENT agent on :$PORT (foreground, Ctrl-C to stop)"
echo "   MCP_SERVER_URL=http://localhost:8083/mcp"
echo ""

cd "$AGENT_DIR"
MCP_SERVER_URL=http://localhost:8083/mcp \
  exec "$VENV/bin/python" -m uvicorn server:app --host 0.0.0.0 --port "$PORT" --reload
