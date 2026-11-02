#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then python3 -m venv .venv; fi
if ! .venv/bin/python -c "import fastapi, uvicorn, edge_tts" 2>/dev/null; then
  .venv/bin/python -m pip install -r requirements.txt
fi
printf 'Open http://127.0.0.1:8765 in your browser.\n'
.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8765
