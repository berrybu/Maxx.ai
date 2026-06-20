"""BricksLLM client (hosted Azure OpenAI-compatible proxy), direct httpx, no openai SDK needed."""

from __future__ import annotations

import json
from typing import Any, Callable

from config import get_settings

from .ollama_client import OllamaUnavailable, _strip_reasoning


def _endpoint(model: str) -> str:
    s = get_settings()
    base = s.bricksllm_endpoint.rstrip("/")
    return f"{base}/api/providers/azure/openai/deployments/{model}/chat/completions"


def _post(payload: dict) -> dict:
    s = get_settings()
    if not s.bricksllm_api_key:
        raise OllamaUnavailable("BRICKSLLM_API_KEY is not configured.")
    import httpx
    try:
        resp = httpx.post(
            _endpoint(s.bricksllm_model),
            params={"api-version": s.bricksllm_api_version},
            headers={
                "Authorization": f"Bearer {s.bricksllm_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=120,
        )
        resp.raise_for_status()
    except Exception as e:
        raise OllamaUnavailable(f"BricksLLM call failed: {e}") from e
    return resp.json()


def _base_payload(messages):
    s = get_settings()
    return {"messages": messages, "temperature": s.ollama_temperature, "max_tokens": s.ollama_max_tokens}


def bricks_chat(messages, *, json_mode=False):
    payload = _base_payload(messages)
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    data = _post(payload)
    text = (data["choices"][0]["message"].get("content") or "").strip()
    return text if json_mode else _strip_reasoning(text)


def bricks_vision(
    prompt: str,
    image_data_url: str,
    *,
    system: str = "",
    json_mode: bool = False,
) -> str:
    """Multimodal vision call (gpt-4o): image + text prompt -> text. Used for real OCR."""
    user_content = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": image_data_url}},
    ]
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user_content})
    return bricks_chat(messages, json_mode=json_mode)


def bricks_chat_with_tools(messages, tools, tool_executor, *, max_rounds=5):
    msgs = list(messages)
    executed = []
    for _ in range(max_rounds):
        payload = _base_payload(msgs)
        payload["tools"] = tools
        data = _post(payload)
        msg = data["choices"][0]["message"]
        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            return {"reply": _strip_reasoning(msg.get("content") or ""), "tool_calls": executed}
        msgs.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": tool_calls})
        for call in tool_calls:
            fn = call.get("function", {})
            name = fn.get("name")
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            try:
                result = tool_executor(name, args); ok = True
            except Exception as e:
                result = {"error": str(e)}; ok = False
            executed.append({"name": name, "args": args, "result": result, "ok": ok})
            msgs.append({"role": "tool", "tool_call_id": call.get("id", name or "tool"),
                         "content": json.dumps(result, ensure_ascii=False, default=str)})
    data = _post(_base_payload(msgs))
    final = data["choices"][0]["message"].get("content") or ""
    return {"reply": _strip_reasoning(final), "tool_calls": executed}
