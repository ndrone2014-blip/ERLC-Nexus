#!/usr/bin/env sh
# Website + Discord bot with a public https:// link (Cloudflare Tunnel).
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
  echo "[FAIL] ERLC Nexus is not installed yet. Run ./install.sh first."
  exit 1
fi
exec .venv/bin/python run.py online
