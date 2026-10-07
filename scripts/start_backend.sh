#!/usr/bin/env bash
# One-command backend startup: creates venv, installs deps, seeds (if empty) and serves on :8000.
set -euo pipefail
cd "$(dirname "$0")/../backend"
PY=${PYTHON:-python3}
if [ ! -d .venv ]; then
  echo "Creating virtualenv…"; $PY -m venv .venv
fi
./.venv/bin/pip install -q -r requirements.txt
echo "CareFlow API → http://localhost:8000  (docs: /docs)"
exec ./.venv/bin/uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}"
