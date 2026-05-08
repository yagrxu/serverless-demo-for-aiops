#!/usr/bin/env bash
# Quick health check for the local dev stack.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

check() {
  local name="$1" url="$2"
  if curl -fsS -o /dev/null -m 2 "$url"; then
    printf "  \033[1;32mok\033[0m   %-18s %s\n" "$name" "$url"
  else
    printf "  \033[1;31mdown\033[0m %-18s %s\n" "$name" "$url"
  fi
}

echo "docker services:"
docker compose ps 2>/dev/null || echo "  (compose not running)"

echo
echo "endpoints:"
check "ddb"         "http://localhost:8001"
check "api"         "http://localhost:8000/_ping"
check "langgraph"   "http://localhost:8081/ping"
check "strands"     "http://localhost:8082/ping"
check "ui/chatbot"  "http://localhost:5173"
check "ui/device"   "http://localhost:5174"
check "ui/admin"    "http://localhost:5175"
