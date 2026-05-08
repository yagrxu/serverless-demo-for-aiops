#!/usr/bin/env bash
# Open an agent folder in VS Code.
#
#   ./local/scripts/open-agent.sh langgraph
#   ./local/scripts/open-agent.sh strands
#   ./local/scripts/open-agent.sh all        # open both

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# Find the VS Code CLI — try PATH first, then common macOS locations.
find_code() {
  if command -v code >/dev/null 2>&1; then
    echo "code"
  elif [[ -x "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code" ]]; then
    echo "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code"
  elif [[ -x "$HOME/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code" ]]; then
    echo "$HOME/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code"
  else
    echo ""
  fi
}

CODE_CMD="$(find_code)"
if [[ -z "$CODE_CMD" ]]; then
  echo "error: VS Code CLI not found."
  echo "Install it: VS Code → Cmd+Shift+P → 'Shell Command: Install code command in PATH'"
  exit 1
fi

usage() { echo "Usage: $0 <langgraph|strands|all>"; exit 2; }
[[ $# -ge 1 ]] || usage

open_agent() {
  local dir="$REPO_ROOT/agents/$1"
  [[ -d "$dir" ]] || { echo "not found: $dir"; exit 1; }
  echo "opening agents/$1"
  "$CODE_CMD" "$dir"
}

case "$1" in
  langgraph) open_agent langgraph ;;
  strands)   open_agent strands ;;
  all)       open_agent langgraph; open_agent strands ;;
  *)         usage ;;
esac
