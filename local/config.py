"""First Brain configuration (spec section 22) loaded from local/.env."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class BrainSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("local/.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Local LLM (spec section 2: provider configurable, do not hard-code Ollama)
    llm_provider: Literal["ollama", "lmstudio", "none"] = "ollama"
    llm_base_url: str = ""  # empty => resolved per provider
    llm_model: str = "llama3.2"
    llm_api_key: str = ""
    llm_timeout_seconds: float = 90.0

    # First Brain LONG-TERM durable store (duy nhất có trạng thái dài hạn)
    local_long_term_db: str = "local_data/long_term.sqlite3"

    # Second Brain — SHORT-TERM online cache (Internet/Cloud via OpenClaw/ChatGPT/Gemini)
    second_brain_url: str = "http://127.0.0.1:8100"
    second_brain_api_key: str = "dev-local-key"
    second_brain_provider: Literal["openclaw", "chatgpt", "gemini", "custom", "none"] = "openclaw"
    second_brain_model: str = "gpt-4o"
    openclaw_api_key: str = ""
    openclaw_base_url: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""

    # Retrieval behaviour
    memory_top_k: int = 8

    # Privacy policy (spec section 19): local_only | selective | cloud_allowed
    data_policy: Literal["local_only", "selective", "cloud_allowed"] = "selective"

    # Obsidian integration (Phase 8/10)
    obsidian_vault_path: str = ""

    # Local persistence
    cache_ttl_seconds: int = 600
    local_data_dir: str = "local_data"
    request_timeout_seconds: float = 30.0

    @property
    def resolved_llm_base_url(self) -> str:
        if self.llm_base_url.strip():
            return self.llm_base_url.strip().rstrip("/")
        if self.llm_provider == "lmstudio":
            return "http://127.0.0.1:1234/v1"
        if self.llm_provider == "ollama":
            return "http://127.0.0.1:11434"
        return ""


@lru_cache
def get_brain_settings() -> BrainSettings:
    return BrainSettings()
