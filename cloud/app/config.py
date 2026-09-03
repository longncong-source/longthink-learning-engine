"""Application configuration loaded from environment / cloud/.env (spec section 2, 7)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file="cloud/.env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # App
    app_name: str = "LongThink Learning Engine"
    version: str = "1.0.0"
    environment: str = "development"
    log_level: str = "INFO"

    # Second Brain — SHORT-TERM online cache (ephemeral, internet) — NOT long-term
    memory_db_backend: Literal["postgres", "sqlite"] = "sqlite"
    sqlite_path: str = "data/second_brain.sqlite3"
    database_url: str = "postgresql://second_brain:second_brain@localhost:5433/second_brain"
    short_term_ttl_days: int = 7

    # Online LLM for Second (Internet) — openclaw / openai / gemini
    online_llm_provider: Literal["openclaw", "openai", "gemini", "none"] = "openclaw"
    online_llm_model: str = "gpt-4o"
    openclaw_api_key: str = ""
    openclaw_base_url: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""

    # Security (spec sections 18/21)
    memory_api_keys: str = ""
    rate_limit_per_minute: int = 240
    # Browser cross-origin access (dashboard on one host calling another API).
    # Comma-separated origins, or "*" for any (auth is still enforced via API key).
    cors_origins: str = "*"

    # Embeddings - configurable provider & dimension, nothing hard-coded (spec section 7)
    # hash | ollama | openai_compatible | lmstudio (LMStudio = openai_compatible at :1234/v1)
    embedding_provider: Literal["hash", "ollama", "openai_compatible", "lmstudio"] = "hash"
    embedding_model: str = "nomic-embed-text"
    embedding_dimension: int = 384
    embedding_base_url: str = "http://localhost:11434"
    embedding_timeout_seconds: float = 20.0

    # Hybrid search weights (spec section 9) - configurable, not assumed optimal
    weight_semantic: float = 0.60
    weight_keyword: float = 0.20
    weight_importance: float = 0.10
    weight_recency: float = 0.10
    recency_half_life_days: float = 30.0

    # Memory quality control (spec section 35)
    dedupe_threshold: float = 0.92
    max_candidates: int = 2000

    # Documents / RAG ingestion (spec sections 31-32)
    max_upload_mb: int = 200
    chunk_size_chars: int = 1200
    chunk_overlap_chars: int = 150
    documents_importance: float = 0.55
    documents_confidence: float = 0.8

    # Folder watcher: incremental auto-index (VECTOR spec sections 18-19)
    # Poll-based (no extra deps); size+mtime fast path, sha256 on change.
    watch_poll_seconds: int = 60
    watch_max_mb: int = 200

    # Mid Brain (Third Brain - Intelligence Layer)
    mid_brain_first_brain_url: str = "http://127.0.0.1:8100"
    mid_brain_second_brain_url: str = "http://127.0.0.1:8100"
    mid_brain_enable_reflection: bool = True
    mid_brain_enable_learning: bool = True
    mid_brain_enable_conflict_detection: bool = True
    mid_brain_enable_reference: bool = True
    mid_brain_enable_planning: bool = True
    mid_brain_enable_agent: bool = True
    mid_brain_enable_confidence: bool = True
    mid_brain_enable_network: bool = True
    mid_brain_enable_obsidian: bool = False
    mid_brain_obsidian_vault_path: str = ""
    mid_brain_confidence_threshold: float = 0.62

    @property
    def api_key_list(self) -> list[str]:
        return [k.strip() for k in self.memory_api_keys.split(",") if k.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
