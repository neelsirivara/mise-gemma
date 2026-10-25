#!/usr/bin/env bash
# Start Mise from a terminal on macOS / Linux (Windows: run.cmd).
#   ./run.sh                      # Mise
#   ./run.sh mise --dual          # + a second model on the CPU as the always-on watcher
#   ./run.sh mise --dual --phone  # HTTPS on the local network for an iPhone (setup QR on :8080, app on :8443)
#   ./run.sh mise --engine ollama # fallback engine
#   ./run.sh mise --port 9000
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
APP="mise"; ENGINE="litert"; DUAL=0; PHONE=0; PORT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dual) DUAL=1 ;;
    --phone) PHONE=1 ;;
    --engine) ENGINE="$2"; shift ;;
    --port) PORT="$2"; shift ;;
    -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
    *) APP="$1" ;;
  esac
  shift
done
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || { echo "No .venv yet. Run ./setup.sh first."; exit 1; }
export PYTHONUTF8=1 APP GEMMA_ENGINE="$ENGINE" OPEN_BROWSER=1
if [ "$PHONE" = 1 ]; then export PHONE=1; PORT="${PORT:-8443}"; else unset PHONE; PORT="${PORT:-8000}"; fi
export PORT
if [ "$DUAL" = 1 ]; then
  export GEMMA_WATCH_MODEL="$ROOT/models/gemma-4-E2B-it.litertlm" GEMMA_WATCH_BACKEND=cpu
else
  unset GEMMA_WATCH_MODEL
fi
cd "$ROOT"
exec "$PY" -m core.server "$APP"
