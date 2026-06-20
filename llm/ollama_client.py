"""Ollama LLM client (based on LangChain ChatOllama)."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any, Callable, Optional

from config import get_settings


class OllamaUnavailable(RuntimeError):
    """Raised when the Ollama service is unreachable or the model has not been pulled."""


_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_HARMONY_FINAL = re.compile(r"^.*<\|channel\|>final\b\s*<\|[a-z_]+\|>", re.DOTALL | re.IGNORECASE)
_HARMONY_TOKENS = re.compile(r"<\|[a-z_]+\|>", re.IGNORECASE)


def _strip_reasoning(text: str) -> str:
    if not text:
        return text
    if "<|channel|>final" in text:
        text = _HARMONY_FINAL.sub("", text)
    text = _THINK_BLOCK.sub("", text)
    text = _HARMONY_TOKENS.sub("", text)
    text = re.sub(r"^\s*assistant(final)?\s*", "", text, flags=re.IGNORECASE)
    return text.strip()


@lru_cache(maxsize=8)
def _resolve_model(base_url: str, configured: str) -> str:
    try:
        import httpx

        resp = httpx.get(f"{base_url.rstrip('/')}/api/tags", timeout=5)
        resp.raise_for_status()
        models = [m.get("name", "") for m in resp.json().get("models", []) if m.get("name")]
    except Exception:
        return configured
    if not models:
        return configured
    if configured in models:
        return configured
    base = configured.split(":")[0]
    for m in models:
        if m.split(":")[0] == base:
            return m
    fallback = models[0]
    print(f"[Ollama] configured model {configured!r} is not installed, automatically using {fallback!r}."
          f" Run `ollama pull {configured}` or set OLLAMA_MODEL in .env.")
    return fallback


def _build_chat(json_mode: bool = False):
    try:
        from langchain_community.chat_models import ChatOllama
    except Exception as e:
        raise OllamaUnavailable("langchain_community is not installed, run `pip install -r requirements.txt`") from e
    s = get_settings()
    model = _resolve_model(s.ollama_base_url, s.ollama_model)
    kwargs: dict[str, Any] = dict(model=model, base_url=s.ollama_base_url,
                                  temperature=s.ollama_temperature, num_predict=s.ollama_max_tokens)
    if json_mode:
        kwargs["format"] = "json"
    return ChatOllama(**kwargs)


def _to_lc_messages(messages):
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
    out = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if role == "system":
            out.append(SystemMessage(content=content))
        elif role == "assistant":
            out.append(AIMessage(content=content))
        else:
            out.append(HumanMessage(content=content))
    return out


def chat(messages, *, json_mode: bool = False) -> str:
    chat_model = _build_chat(json_mode=json_mode)
    try:
        result = chat_model.invoke(_to_lc_messages(messages))
    except Exception as e:
        raise OllamaUnavailable(f"Ollama call failed: {e}") from e
    text = (result.content or "").strip()
    return text if json_mode else _strip_reasoning(text)


def chat_json(messages) -> dict:
    text = chat(messages, json_mode=True)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start:end + 1])
        raise


def chat_with_tools(messages, tools, tool_executor, *, max_rounds: int = 5) -> dict:
    from langchain_core.messages import AIMessage, ToolMessage
    chat_model = _build_chat()
    try:
        bound = chat_model.bind_tools(tools)
    except Exception as e:
        raise OllamaUnavailable(f"The current Ollama model does not support tool calling: {e}") from e
    lc_messages = _to_lc_messages(messages)
    executed: list[dict] = []
    for _ in range(max_rounds):
        try:
            ai = bound.invoke(lc_messages)
        except Exception as e:
            raise OllamaUnavailable(f"Ollama call (tool mode) failed: {e}") from e
        lc_messages.append(ai)
        tool_calls = getattr(ai, "tool_calls", None) or []
        if not tool_calls:
            return {"reply": _strip_reasoning(ai.content or ""), "tool_calls": executed}
        for call in tool_calls:
            name = call.get("name")
            args = call.get("args", {}) or {}
            try:
                result = tool_executor(name, args)
                ok = True
            except Exception as e:
                result = {"error": str(e)}
                ok = False
            executed.append({"name": name, "args": args, "result": result, "ok": ok})
            lc_messages.append(ToolMessage(content=json.dumps(result, ensure_ascii=False, default=str),
                                           tool_call_id=call.get("id", name or "tool")))
    final = bound.invoke(lc_messages)
    return {"reply": _strip_reasoning(final.content or ""), "tool_calls": executed}


LLMUnavailable = OllamaUnavailable
