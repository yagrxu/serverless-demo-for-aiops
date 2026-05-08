#!/usr/bin/env bash
# Bring up the full laptop dev stack.
#
#   ./local/scripts/up.sh              # start everything
#   ./local/scripts/up.sh --no-ui      # backend + agents only
#   ./local/scripts/up.sh --no-seed    # skip the seed step
#   ./local/scripts/up.sh --no-agents  # docker + MCP server + seed only, start agents yourself
#   ./local/scripts/up.sh --no-mcp     # skip MCP server (agents call API directly)
#
# Docker runs: DynamoDB Local + API shim.
# MCP Server + Agents run on the host so they inherit your AWS credentials.
# UIs run on the host via Vite dev servers.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

RUN_UI=true
RUN_SEED=true
RUN_AGENTS=true
RUN_MCP=true
for arg in "$@"; do
  case "$arg" in
    --no-ui)     RUN_UI=false ;;
    --no-seed)   RUN_SEED=false ;;
    --no-agents) RUN_AGENTS=false ;;
    --no-mcp)    RUN_MCP=false ;;
    -h|--help)
      sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown arg: $arg"; exit 2 ;;
  esac
done

PID_DIR="$REPO_ROOT/local/.run"
LOG_DIR="$REPO_ROOT/local/.logs"
mkdir -p "$PID_DIR" "$LOG_DIR"

say()  { printf "\033[1;34m>> %s\033[0m\n" "$*"; }
warn() { printf "\033[1;33m!! %s\033[0m\n" "$*"; }
die()  { printf "\033[1;31mxx %s\033[0m\n" "$*" >&2; exit 1; }

# ---------- prereq checks ----------
say "checking prerequisites"
command -v docker  >/dev/null || die "docker not found"
docker compose version >/dev/null 2>&1 || die "docker compose v2 not found"
command -v aws     >/dev/null || die "aws cli not found"
command -v python3 >/dev/null || die "python3 not found (needed for MCP server and agents)"
if $RUN_UI; then
  command -v node >/dev/null || die "node not found (needed for UIs)"
  command -v npm  >/dev/null || die "npm not found (needed for UIs)"
fi

# ---------- docker backend (DDB + API only) ----------
say "docker compose up (ddb, api)"
docker compose up -d --build

say "waiting for DynamoDB Local"
for _ in $(seq 1 30); do
  if aws dynamodb list-tables --endpoint-url http://localhost:8001 \
       --region us-east-1 >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
aws dynamodb list-tables --endpoint-url http://localhost:8001 --region us-east-1 >/dev/null \
  || die "DynamoDB Local did not come up on :8001"

say "waiting for API"
for _ in $(seq 1 30); do
  if curl -fsS http://localhost:8000/_ping >/dev/null 2>&1; then break; fi
  sleep 1
done
curl -fsS http://localhost:8000/_ping >/dev/null \
  || die "API did not come up on :8000 — check 'docker compose logs api'"

# ---------- ddb tables + seed ----------
say "creating DynamoDB tables (idempotent)"
DDB_ENDPOINT=http://localhost:8001 "$REPO_ROOT/local/scripts/init-ddb.sh"

if $RUN_SEED; then
  say "seeding sample data"
  API=http://localhost:8000 "$REPO_ROOT/local/scripts/seed.sh" || warn "seed failed (ok on re-runs)"
fi

# ---------- MCP Server (run on host, before agents) ----------
if $RUN_MCP; then
  MCP_DIR="$REPO_ROOT/mcp-server"
  MCP_VENV="$MCP_DIR/.venv"

  # Create venv and install deps if needed
  if [[ ! -d "$MCP_VENV" ]]; then
    say "creating venv for mcp-server"
    python3 -m venv "$MCP_VENV"
    "$MCP_VENV/bin/pip" install --quiet -r "$MCP_DIR/requirements.txt"
  fi

  pidfile="$PID_DIR/mcp-server.pid"
  if [[ -f "$pidfile" ]] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
    warn "mcp-server already running (pid $(cat "$pidfile")) — skipping"
  else
    say "starting mcp-server on :8083"
    (cd "$MCP_DIR" && \
     API_URL=http://localhost:8000 \
     nohup "$MCP_VENV/bin/python" server.py \
       >"$LOG_DIR/mcp-server.log" 2>&1 &
     echo $! > "$pidfile")
  fi

  say "waiting for MCP Server"
  for _ in $(seq 1 15); do
    if curl -fsS -o /dev/null http://localhost:8083/health 2>/dev/null; then break; fi
    sleep 1
  done
  curl -fsS -o /dev/null http://localhost:8083/health 2>/dev/null \
    || warn "MCP Server not responding on :8083 — check $LOG_DIR/mcp-server.log"
fi

# ---------- agents (run on host, after MCP Server) ----------
if $RUN_AGENTS; then
  start_agent() {
    local name="$1" port="$2" dir="$3"
    local pidfile="$PID_DIR/agent-$name.pid"
    if [[ -f "$pidfile" ]] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
      warn "agent/$name already running (pid $(cat "$pidfile")) — skipping"
      return
    fi

    # Create venv and install deps if needed
    local venv="$dir/.venv"
    if [[ ! -d "$venv" ]]; then
      say "creating venv for agent/$name"
      python3 -m venv "$venv"
      "$venv/bin/pip" install --quiet -r "$dir/requirements.txt"
    fi

    say "starting agent/$name on :$port"
    (cd "$dir" && \
     MCP_SERVER_URL=http://localhost:8083/mcp \
     nohup "$venv/bin/python" -m uvicorn server:app --host 0.0.0.0 --port "$port" \
       >"$LOG_DIR/agent-$name.log" 2>&1 &
     echo $! > "$pidfile")
  }
  start_agent langgraph 8081 "$REPO_ROOT/agents/langgraph"
  start_agent strands   8082 "$REPO_ROOT/agents/strands"

  say "waiting for agents"
  for _ in $(seq 1 15); do
    lg=$(curl -fsS -o /dev/null -w "%{http_code}" http://localhost:8081/ping 2>/dev/null || echo "000")
    st=$(curl -fsS -o /dev/null -w "%{http_code}" http://localhost:8082/ping 2>/dev/null || echo "000")
    if [[ "$lg" == "200" && "$st" == "200" ]]; then break; fi
    sleep 1
  done
  curl -fsS http://localhost:8081/ping >/dev/null 2>&1 \
    || warn "langgraph agent not responding on :8081 — check $LOG_DIR/agent-langgraph.log"
  curl -fsS http://localhost:8082/ping >/dev/null 2>&1 \
    || warn "strands agent not responding on :8082 — check $LOG_DIR/agent-strands.log"
fi

# ---------- UIs ----------
if $RUN_UI; then
  for ui in chatbot device-simulator admin-console; do
    dir="$REPO_ROOT/ui/$ui"
    if [[ ! -d "$dir/node_modules" ]]; then
      say "installing deps for ui/$ui"
      (cd "$dir" && npm install --silent)
    fi
  done

  start_ui() {
    local name="$1" port="$2"
    local pidfile="$PID_DIR/ui-$name.pid"
    if [[ -f "$pidfile" ]] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
      warn "ui/$name already running (pid $(cat "$pidfile")) — skipping"
      return
    fi
    say "starting ui/$name on :$port"
    (cd "$REPO_ROOT/ui/$name" && nohup npm run dev >"$LOG_DIR/ui-$name.log" 2>&1 &
     echo $! > "$pidfile")
  }
  # Chatbot uses Next.js (port 3000) with LOCAL_MODE
  start_chatbot() {
    local pidfile="$PID_DIR/ui-chatbot.pid"
    if [[ -f "$pidfile" ]] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
      warn "ui/chatbot already running (pid $(cat "$pidfile")) — skipping"
      return
    fi
    say "starting ui/chatbot (Next.js) on :3000"
    (cd "$REPO_ROOT/ui/chatbot" && \
     LOCAL_MODE=true \
     LANGGRAPH_URL=http://localhost:8081 \
     STRANDS_URL=http://localhost:8082 \
     API_URL=http://localhost:8000 \
     nohup npm run dev >"$LOG_DIR/ui-chatbot.log" 2>&1 &
     echo $! > "$pidfile")
  }
  start_chatbot
fi

# ---------- summary ----------
cat <<EOF

$(say 'stack is up')

  DynamoDB Local     http://localhost:8001
  API                http://localhost:8000   (health: /_ping)
EOF

if $RUN_MCP; then
  cat <<EOF
  MCP Server         http://localhost:8083   (health: /health)
EOF
fi

if $RUN_AGENTS; then
  cat <<EOF
  LangGraph agent    http://localhost:8081   (health: /ping)
  Strands agent      http://localhost:8082   (health: /ping)

Agent logs:    $LOG_DIR/agent-*.log
Agent pids:    $PID_DIR/agent-*.pid
EOF
fi

if $RUN_UI; then
  cat <<EOF
  Chatbot UI         http://localhost:3000   (Next.js, LOCAL_MODE)
  Device Simulator   http://localhost:3000/device-simulator
  Admin Console      http://localhost:3000/admin-console

UI logs:    $LOG_DIR/ui-chatbot.log
UI pids:    $PID_DIR/ui-chatbot.pid
EOF
fi

cat <<EOF

MCP Server log:  $LOG_DIR/mcp-server.log
Docker logs:     docker compose logs -f <service>
Tear down:       ./local/scripts/down.sh
EOF
