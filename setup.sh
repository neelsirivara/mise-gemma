#!/usr/bin/env bash
# One-time setup on macOS (Apple Silicon) or Linux: Python venv, dependencies, ~3 GB of models.
#   ./setup.sh            # everything
#   ./setup.sh --no-models
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [ "$(uname)" = "Darwin" ] && [ "$(uname -m)" != "arm64" ]; then
  echo "Note: LiteRT-LM ships macOS wheels for Apple Silicon only. On an Intel Mac use: ./run.sh mise --engine ollama"
fi

# Python 3.10-3.13 (3.12 recommended). Prefer uv if present, else python3.12 / python3.
if command -v uv >/dev/null 2>&1; then
  uv venv --python 3.12 .venv
  PIP="uv pip install --python .venv/bin/python"
else
  PYBIN="$(command -v python3.12 || command -v python3)"
  "$PYBIN" -m venv .venv
  .venv/bin/python -m pip install --upgrade pip -q
  PIP=".venv/bin/python -m pip install -q"
fi
$PIP -r requirements.txt

if [ "${1:-}" != "--no-models" ]; then
  .venv/bin/python scripts/download_models.py
fi
chmod +x run.sh
echo
echo "Done. Start Mise with:  ./run.sh mise --dual"
echo "Phone (iPhone home-screen app):  ./run.sh mise --dual --phone   then see PHONE.md"
