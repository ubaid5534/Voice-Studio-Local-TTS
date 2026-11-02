#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then python3 -m venv .venv; fi
.venv/bin/python -m pip install -r requirements-offline.txt
printf 'Piper installed. Next download models inside Voice Studio.\n'
