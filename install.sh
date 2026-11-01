#!/usr/bin/env bash
# ERLC Nexus installer for Linux / macOS (optional — Windows users use install.bat)
set -euo pipefail
cd "$(dirname "$0")"
PY=""
for c in python3.13 python3.12 python3; do
  if command -v "$c" >/dev/null && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)'; then PY="$c"; break; fi
done
[ -z "$PY" ] && { echo "[FAIL] Python 3.12+ is required."; exit 1; }
echo "[ OK ] Using $($PY --version)"
[ -x .venv/bin/python ] || "$PY" -m venv .venv
.venv/bin/python -m pip install --upgrade pip -q
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/setup.py
