#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
command -v python3 >/dev/null || { echo 'Python 3 required'; exit 1; }
command -v npm >/dev/null || { echo 'Node.js and npm required'; exit 1; }
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements.txt
(cd frontend && npm install)
echo 'Installed. Run ./scripts/dev.sh'
