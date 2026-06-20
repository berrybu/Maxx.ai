"""Low-level email-sending implementation (shared by the MCP service and the local fallback path)."""

from __future__ import annotations

import json
import os
import smtplib
import time
from email.mime.text import MIMEText
from typing import Any

from config import get_settings

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_OUTBOX = os.path.join(_ROOT, "outbox.json")


def _append_outbox(record: dict) -> None:
    data = []
    if os.path.exists(_OUTBOX):
        try:
            with open(_OUTBOX, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = []
    data.append(record)
    tmp = _OUTBOX + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _OUTBOX)


def send_email(to: str, subject: str, body: str) -> dict[str, Any]:
    s = get_settings()
    if not to or "@" not in to:
        return {"ok": False, "error": f"invalid recipient email: {to!r}"}
    record = {"to": to, "from": s.email_from, "subject": subject, "body": body,
              "t": time.strftime("%Y-%m-%d %H:%M:%S"), "message_id": f"<{int(time.time()*1000)}@maxx>"}
    if s.email_mock or not s.smtp_host:
        record["mode"] = "mock"
        _append_outbox(record)
        return {"ok": True, "mode": "mock", "to": to, "subject": subject,
                "message_id": record["message_id"], "note": "EMAIL_MOCK enabled, email written to outbox.json"}
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = s.email_from
        msg["To"] = to
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=30) as server:
            server.starttls()
            if s.smtp_user:
                server.login(s.smtp_user, s.smtp_password)
            server.sendmail(s.email_from, [to], msg.as_string())
        record["mode"] = "smtp"
        _append_outbox(record)
        return {"ok": True, "mode": "smtp", "to": to, "subject": subject, "message_id": record["message_id"]}
    except Exception as e:
        return {"ok": False, "error": f"SMTP send failed: {e}"}
