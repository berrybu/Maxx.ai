"""MCP client bridge -- lets this process's Agent call the email service via the MCP protocol."""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


async def _call_via_mcp(tool: str, args: dict) -> dict:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=sys.executable, args=["-m", "mcp_server.email_server"],
                                   cwd=_ROOT, env={**os.environ, "PYTHONPATH": _ROOT})
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool, args)
            data: Any = None
            if getattr(result, "structuredContent", None):
                data = result.structuredContent
            elif result.content:
                block = result.content[0]
                text = getattr(block, "text", None)
                if text:
                    import json
                    try:
                        data = json.loads(text)
                    except Exception:
                        data = {"raw": text}
            if isinstance(data, dict) and "result" in data and len(data) == 1:
                data = data["result"]
            return data if isinstance(data, dict) else {"ok": True, "result": data}


def send_email_via_mcp(to: str, subject: str, body: str) -> dict:
    args = {"to": to, "subject": subject, "body": body}
    try:
        result = asyncio.run(_call_via_mcp("send_email", args))
        result.setdefault("transport", "mcp")
        return result
    except Exception as e:
        from agent.email_tool import send_email
        result = send_email(to=to, subject=subject, body=body)
        result["transport"] = "direct"
        result["mcp_error"] = str(e)
        return result
