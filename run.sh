#!/usr/bin/env bash
# ===== Verity — local test launcher (Mac / Linux). Run:  ./run.sh =====
cd "$(dirname "$0")"
PY=python3; command -v $PY >/dev/null || PY=python

if [ ! -d .venv ]; then
  echo "Creating a local environment (first run only)..."
  $PY -m venv .venv
fi
source .venv/bin/activate

echo "Installing components (first run only, about 1-2 minutes)..."
pip install --upgrade pip -q
pip install -r requirements.txt -q

export SEED_DEMO=1
echo
echo "====================================================="
echo "  Verity v2 is starting on YOUR computer only."
echo "  Open a browser at:   http://localhost:5000"
echo "  Sign in:  lead@verity.local   /   Verity2026"
echo "  Press Ctrl+C to stop."
echo "====================================================="
echo
( sleep 2; (command -v open >/dev/null && open http://localhost:5000) \
  || (command -v xdg-open >/dev/null && xdg-open http://localhost:5000) ) >/dev/null 2>&1 &
python app.py
