#!/usr/bin/env bash
# One-command frontend startup on :3000.
set -euo pipefail
cd "$(dirname "$0")/../frontend"
[ -d node_modules ] || npm install --no-audit --no-fund
echo "CareFlow UI → http://localhost:3000"
exec npm run dev
