#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -d backend/.venv || ! -d frontend/node_modules ]]; then echo 'Run scripts/install.sh first'; exit 1; fi
backend/.venv/bin/uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 &
pid=$!
trap 'kill "$pid" 2>/dev/null || true' EXIT
cd frontend
npm run dev
