#!/usr/bin/env bash
# Send a real test email to verify SMTP configuration. Usage: ./test_email.sh recipient@example.com
set -euo pipefail
cd "$(dirname "$0")"

if [ -f .env ]; then set -a; . ./.env; set +a; fi
export PYTHONPATH="$PWD"

TO="${1:-}"
if [ -z "$TO" ]; then
  echo "Usage: ./test_email.sh recipient@example.com" >&2
  exit 1
fi

python3 - "$TO" <<'PYEOF'
import sys
from agent.email_tool import send_email
res = send_email(sys.argv[1], "Maxx test email", "This is a real SMTP test email from Maxx.")
print(res)
mode = res.get("mode")
if mode == "smtp":
    print("✅ Real send succeeded (mode=smtp)")
elif mode == "mock":
    print("⚠️  Still mock: check EMAIL_MOCK=0 and SMTP_HOST is set in .env")
else:
    print("❌ Send failed: ", res.get("error"))
PYEOF
