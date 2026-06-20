#!/usr/bin/env bash
# Start Maxx (reads real credentials from .env). Usage: ./run.sh
# Secrets stay only in local .env (ignored by .gitignore), never committed to source.
set -euo pipefail
cd "$(dirname "$0")"

if [ -f .env ]; then
  set -a            # auto-export sourced variables
  . ./.env
  set +a
else
  echo "⚠️  .env not found, first run: cp .env.example .env and fill in credentials" >&2
fi

export PYTHONPATH="$PWD"
PORT="${PORT:-8010}"

echo "Maxx starting → http://127.0.0.1:${PORT}/"
echo "  LLM_PROVIDER=${LLM_PROVIDER:-?}  EMAIL_MOCK=${EMAIL_MOCK:-1}  SMTP_HOST=${SMTP_HOST:-<unset>}"
exec python3 -m uvicorn api.main:app --host 127.0.0.1 --port "${PORT}" --log-level warning
