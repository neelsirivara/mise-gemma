#!/bin/bash
# Double-click in Finder (or drag to the Dock) to start Mise. Opens the Hub page in your browser.
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
  echo "Mise is not set up yet. Run ./setup.sh first"
  read -r -p "Press Enter to close..." _
  exit 1
fi
exec .venv/bin/python -m core.launcher
