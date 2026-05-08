#!/usr/bin/env bash
# Tear down everything started by up.sh.
#
#   ./local/scripts/down.sh          # stop agents + UIs + containers
#   ./local/scripts/down.sh --purge  # also prune docker images/volumes + wipe logs

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

PURGE=false
for arg in "$@"; do
  case "$arg" in
    --purge) PURGE=true ;;
    -h|--help) sed -n '2,6p' "$0"; exit 0 ;;
    *) echo "unknown arg: $arg"; exit 2 ;;
  esac
done

PID_DIR="$REPO_ROOT/local/.run"
LOG_DIR="$REPO_ROOT/local/.logs"

say()  { printf "\033[1;34m>> %s\033[0m\n" "$*"; }
warn() { printf "\033[1;33m!! %s\033[0m\n" "$*"; }

# ---------- stop agents + UIs ----------
if [[ -d "$PID_DIR" ]]; then
  shopt -s nullglob
  for pidfile in "$PID_DIR"/*.pid; do
    name="$(basename "$pidfile" .pid)"
    pid="$(cat "$pidfile" 2>/dev/null || true)"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      say "stopping $name (pid $pid)"
      pkill -P "$pid" 2>/dev/null || true
      kill "$pid" 2>/dev/null || true
      sleep 0.5
      kill -9 "$pid" 2>/dev/null || true
    else
      warn "$name not running"
    fi
    rm -f "$pidfile"
  done
  shopt -u nullglob
fi

# Belt-and-suspenders: anything still listening on known ports.
for port in 3000 8081 8082 8083; do
  if command -v lsof >/dev/null 2>&1; then
    pids="$(lsof -ti ":$port" 2>/dev/null || true)"
    if [[ -n "$pids" ]]; then
      warn "killing leftover listeners on :$port ($pids)"
      kill $pids 2>/dev/null || true
    fi
  fi
done

# ---------- stop docker ----------
say "docker compose down"
if $PURGE; then
  docker compose down --volumes --rmi local --remove-orphans
else
  docker compose down --remove-orphans
fi

# ---------- clean state dir ----------
rm -rf "$PID_DIR"
if $PURGE; then rm -rf "$LOG_DIR"; fi

say "stack is down"
