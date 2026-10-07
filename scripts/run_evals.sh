#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
exec backend/.venv/bin/python evals/run_evals.py "$@"
