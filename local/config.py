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
    # ollama (11434 native /api/chat) | lmstudio (1234/v1 OpenAI-compat) |
    # deepseek (api.deepseek.com/v1 OpenAI-compat, needs DEEPSEEK_API_KEY) |
    # openai_compatible (any /v1 base via LLM_BASE_URL) | openclaw (OpenAI-compat
    #   endpoint via OPENCLAW_BASE_URL, e.g. a local OpenClaw proxy) | none (offline extractive)
    llm_provider: Literal["ollama", "lmstudio", "deepseek", "openai_compatible", "openclaw", "none"] = "ollama"
    llm_base_url: str = ""  # empty => resolved per provider
    llm_model: str = "llama3.2"
    llm_api_key: str = ""
    deepseek_api_key: str = ""
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

    # Turn trace (tini-agent pattern: always-on JSONL, zero setup)
    trace_enabled: bool = True
    trace_dir: str = ""  # empty => <local_data_dir>/traces

    # Consolidation (tini-agent pattern: distill raw turns into durable facts)
    consolidate_every: int = 6  # run after this many unconsolidated turns (0 = off)

    @property
    def resolved_llm_base_url(self) -> str:
        if self.llm_provider == "openclaw":
            # OpenClaw gateway (:18790) is WebSocket RPC, NOT OpenAI-compatible.
            # Priority: OPENCLAW_BASE_URL > LLM_BASE_URL > "" (offline fallback,
            # never silently misroute to another provider's endpoint).
            if self.openclaw_base_url.strip():
                return self.openclaw_base_url.strip().rstrip("/")
            if self.llm_base_url.strip():
                return self.llm_base_url.strip().rstrip("/")
            return ""
        if self.llm_base_url.strip():
            return self.llm_base_url.strip().rstrip("/")
        if self.llm_provider == "lmstudio":
            return "http://127.0.0.1:1234/v1"
        if self.llm_provider == "ollama":
            return "http://127.0.0.1:11434"
        if self.llm_provider == "deepseek":
            return "https://api.deepseek.com/v1"
        return ""

    @property
    def resolved_llm_api_key(self) -> str:
        """LLM_API_KEY wins; DEEPSEEK_API_KEY is the fallback for provider=deepseek."""
        if self.llm_provider == "openclaw":
            if self.openclaw_api_key.strip():
                return self.openclaw_api_key.strip()
            return self.llm_api_key.strip()
        if self.llm_api_key.strip():
            return self.llm_api_key.strip()
        if self.llm_provider == "deepseek":
            return self.deepseek_api_key.strip()
        return ""

    @property
    def openclaw_configured(self) -> bool:
        """True when an OpenAI-compatible OpenClaw endpoint + key are configured."""
        return bool(self.openclaw_base_url.strip()) and bool(self.openclaw_api_key.strip())

    @property
    def openclaw_integration_warning(self) -> str:
        """Advisory text when SECOND_BRAIN_PROVIDER=openclaw but OPENCLAW_* is empty.

        OPENCLAW_* was previously dead config (never read by code). It is now
        wired as an OpenAI-compatible endpoint, but an empty base_url/key means
        the online LLM is unconfigured and the loop uses offline fallback.
        """
        if self.second_brain_provider == "openclaw" and not self.openclaw_configured:
            return (
                "SECOND_BRAIN_PROVIDER=openclaw but OPENCLAW_BASE_URL/OPENCLAW_API_KEY "
                "are empty - online LLM unconfigured, offline fallback active. "
                "Set OPENCLAW_BASE_URL to an OpenAI-compatible endpoint to enable it."
            )
        return ""


@lru_cache
def get_brain_settings() -> BrainSettings:
    return BrainSettings()
