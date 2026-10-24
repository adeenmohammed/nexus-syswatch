#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
command -v python3 >/dev/null || { echo "Python 3 is required."; exit 1; }
python3 - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit("Python 3.10+ is required.")
PY
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install --upgrade pip
backend/.venv/bin/python -m pip install "psutil>=6,<8"
chmod +x scripts/terminal.sh
echo
echo "Terminal monitor installed."
echo "Run: ./scripts/terminal.sh"
