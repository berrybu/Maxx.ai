"""Unified LLM entry point: dispatches to Ollama or BricksLLM based on settings.llm_provider."""

from __future__ import annotations

import json

from config import get_settings

from . import bricks_client, ollama_client
from .ollama_client import LLMUnavailable, OllamaUnavailable

__all__ = ["chat", "chat_json", "chat_with_tools", "vision", "OllamaUnavailable", "LLMUnavailable"]


def _provider():
    return get_settings().llm_provider


def chat(messages, *, json_mode=False):
    if _provider() == "bricksllm":
        return bricks_client.bricks_chat(messages, json_mode=json_mode)
    return ollama_client.chat(messages, json_mode=json_mode)


def chat_json(messages):
    text = chat(messages, json_mode=True)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{"); end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start:end + 1])
        raise


def chat_with_tools(messages, tools, tool_executor, *, max_rounds=5):
    if _provider() == "bricksllm":
        return bricks_client.bricks_chat_with_tools(messages, tools, tool_executor, max_rounds=max_rounds)
    return ollama_client.chat_with_tools(messages, tools, tool_executor, max_rounds=max_rounds)


def vision(prompt: str, image_data_url: str, *, system: str = "", json_mode: bool = False) -> str:
    """Multimodal vision recognition (real OCR). Only supported by BricksLLM gpt-4o."""
    if _provider() == "bricksllm":
        return bricks_client.bricks_vision(prompt, image_data_url, system=system, json_mode=json_mode)
    raise OllamaUnavailable("OCR/vision requires gpt-4o, please set LLM_PROVIDER=bricksllm.")
