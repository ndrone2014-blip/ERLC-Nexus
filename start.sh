#!/usr/bin/env bash
cd "$(dirname "$0")"
[ -x .venv/bin/python ] || { echo "Run ./install.sh first."; exit 1; }
exec .venv/bin/python run.py "$@"
