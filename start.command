#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [ -d .tools/export-runtime ]; then
  export PYTHONPATH="$PWD/.tools/export-runtime${PYTHONPATH:+:$PYTHONPATH}"
fi
app_python="${GOLDEN_GATE_PYTHON:-python3}"
if [ -x .venv/bin/python ]; then
  app_python=.venv/bin/python
elif ! "$app_python" -c 'import fastapi, uvicorn, openpyxl, multipart, reportlab, PIL' 2>/dev/null; then
  if [ -x "$HOME/miniconda3/bin/python3" ] && "$HOME/miniconda3/bin/python3" -c 'import fastapi, uvicorn, openpyxl, multipart, reportlab, PIL' 2>/dev/null; then
    app_python="$HOME/miniconda3/bin/python3"
  else
    "$app_python" -m venv .venv
    .venv/bin/python -m pip install -r requirements.txt
    app_python=.venv/bin/python
  fi
fi
if ! "$app_python" -c 'import fastapi, uvicorn, openpyxl, multipart, reportlab, PIL' 2>/dev/null; then
  "$app_python" -m pip install -r requirements.txt
fi
printf '\nJunction is available at http://127.0.0.1:%s\nPress Ctrl+C to stop.\n\n' "${GOLDEN_GATE_PORT:-8765}"
exec "$app_python" -m uvicorn app.main:app --host "${GOLDEN_GATE_HOST:-127.0.0.1}" --port "${GOLDEN_GATE_PORT:-8765}"
