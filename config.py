"""Maxx global configuration. All external credentials are read from environment variables / .env, never hardcoded."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv optional
    pass


def _bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    cala_api_key: str = os.environ.get("CALA_API_KEY", "")
    cala_base_url: str = os.environ.get("CALA_BASE_URL", "https://api.cala.ai")

    llm_provider: str = os.environ.get("LLM_PROVIDER", "ollama").strip().lower()

    ollama_base_url: str = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    ollama_model: str = os.environ.get("OLLAMA_MODEL", "qwen3:8b")
    ollama_temperature: float = float(os.environ.get("OLLAMA_TEMPERATURE", "0.3"))
    ollama_max_tokens: int = int(os.environ.get("OLLAMA_MAX_TOKENS", "2048"))

    bricksllm_api_key: str = os.environ.get("BRICKSLLM_API_KEY", "")
    bricksllm_endpoint: str = os.environ.get("BRICKSLLM_ENDPOINT", "https://bricksllm.chatbmw-secure.azure.bmw.cloud")
    bricksllm_model: str = os.environ.get("BRICKSLLM_MODEL", "gpt-4o")
    bricksllm_api_version: str = os.environ.get("BRICKSLLM_API_VERSION", "2024-10-21")

    email_mock: bool = _bool("EMAIL_MOCK", True)
    smtp_host: str = os.environ.get("SMTP_HOST", "")
    smtp_port: int = int(os.environ.get("SMTP_PORT", "587") or "587")
    smtp_user: str = os.environ.get("SMTP_USER", "")
    smtp_password: str = os.environ.get("SMTP_PASSWORD", "")
    email_from: str = os.environ.get("EMAIL_FROM", "sales@maxx.example")

    product_doc: str = os.environ.get("PRODUCT_DOC", "")
    seller_name: str = os.environ.get("SELLER_NAME", "Tim")
    seller_company: str = os.environ.get("SELLER_COMPANY", "Maxx Components")
    seller_desc: str = os.environ.get("SELLER_DESC", "German automotive parts manufacturer")

    @property
    def cala_enabled(self) -> bool:
        return bool(self.cala_api_key) and self.cala_api_key != "your_cala_api_key_here"

    @property
    def bricksllm_enabled(self) -> bool:
        return bool(self.bricksllm_api_key)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
