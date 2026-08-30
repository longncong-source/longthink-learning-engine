"""Embedding provider abstraction - configurable, no hard-coded dimensions (spec section 7).

Providers:
    hash              deterministic feature hashing (offline dev/tests, weak semantics)
    ollama            POST {base}/api/embeddings           e.g. nomic-embed-text (768d)
    openai_compatible POST {base}/embeddings               LM Studio, Ollama /v1, etc.
"""

from __future__ import annotations

import hashlib
import math
import re
import threading

import httpx

from cloud.app.config import Settings, get_settings
from cloud.app.errors import UpstreamUnavailableError

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)

_PROVIDER_LOCK = threading.Lock()
_PROVIDER_SINGLETON: "EmbeddingProvider | None" = None


class EmbeddingProvider:
    name = "abstract"
    dimension = 0

    def embed(self, text: str) -> list[float]:  # pragma: no cover - interface
        raise NotImplementedError


class HashEmbedding(EmbeddingProvider):
    """Deterministic offline embedding for development/tests. Weak semantics by design."""

    name = "hash"

    def __init__(self, dimension: int) -> None:
        self.dimension = dimension

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dimension
        tokens = _TOKEN_RE.findall((text or "").lower())
        features = tokens + [f"{a}_{b}" for a, b in zip(tokens, tokens[1:])]
        for feature in features:
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=16).digest()
            idx = int.from_bytes(digest[:8], "big") % self.dimension
            sign = 1.0 if digest[8] % 2 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [round(v / norm, 9) for v in vec]


class OllamaEmbedding(EmbeddingProvider):
    name = "ollama"

    def __init__(self, model: str, base_url: str, dimension: int, timeout: float) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.dimension = dimension
        self.timeout = timeout

    def embed(self, text: str) -> list[float]:
        url = f"{self.base_url}/api/embeddings"
        try:
            resp = httpx.post(url, json={"model": self.model, "prompt": text}, timeout=self.timeout)
            resp.raise_for_status()
            payload = resp.json()
        except httpx.HTTPError as exc:
            raise UpstreamUnavailableError(
                f"Ollama embeddings unavailable at {url}: {exc}",
                details={"provider": self.name, "model": self.model},
            ) from exc
        vector = payload.get("embedding") if isinstance(payload, dict) else None
        if not isinstance(vector, list):
            raise UpstreamUnavailableError("Ollama returned malformed embedding payload")
        return [float(x) for x in vector]


class OpenAICompatibleEmbedding(EmbeddingProvider):
    name = "openai_compatible"

    def __init__(self, model: str, base_url: str, dimension: int, timeout: float, api_key: str = "") -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.dimension = dimension
        self.timeout = timeout
        self.api_key = api_key

    def embed(self, text: str) -> list[float]:
        url = f"{self.base_url}/embeddings"
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            resp = httpx.post(url, json={"model": self.model, "input": [text]}, timeout=self.timeout, headers=headers)
            resp.raise_for_status()
            payload = resp.json()
        except httpx.HTTPError as exc:
            raise UpstreamUnavailableError(
                f"Embedding endpoint unavailable at {url}: {exc}",
                details={"provider": self.name, "model": self.model},
            ) from exc
        try:
            vector = payload["data"][0]["embedding"]
        except (KeyError, IndexError, TypeError) as exc:
            raise UpstreamUnavailableError("OpenAI-compatible endpoint returned malformed embedding") from exc
        return [float(x) for x in vector]


def build_provider(settings: Settings) -> EmbeddingProvider:
    common = (settings.embedding_model, settings.embedding_base_url, settings.embedding_dimension,
              settings.embedding_timeout_seconds)
    if settings.embedding_provider == "hash":
        return HashEmbedding(settings.embedding_dimension)
    if settings.embedding_provider == "ollama":
        return OllamaEmbedding(*common)
    if settings.embedding_provider in ("openai_compatible", "lmstudio"):
        # lmstudio = openai_compatible at 127.0.0.1:1234/v1
        base = settings.embedding_base_url
        if settings.embedding_provider == "lmstudio" and not base.strip():
            base = "http://127.0.0.1:1234/v1"
            common = (settings.embedding_model, base, settings.embedding_dimension, settings.embedding_timeout_seconds)
        return OpenAICompatibleEmbedding(*common)
    raise UpstreamUnavailableError(f"Unknown EMBEDDING_PROVIDER: {settings.embedding_provider}")


def get_embedding_provider(settings: Settings | None = None) -> EmbeddingProvider:
    global _PROVIDER_SINGLETON
    with _PROVIDER_LOCK:
        if _PROVIDER_SINGLETON is None:
            _PROVIDER_SINGLETON = build_provider(settings or get_settings())
        return _PROVIDER_SINGLETON


def reset_embedding_provider() -> None:
    global _PROVIDER_SINGLETON
    with _PROVIDER_LOCK:
        _PROVIDER_SINGLETON = None


def embed_text(text: str, settings: Settings | None = None) -> list[float]:
    s = settings or get_settings()
    provider = get_embedding_provider(s)
    try:
        vector = provider.embed(text)
    except UpstreamUnavailableError:
        raise
    except Exception as exc:  # noqa: BLE001 - surface any provider failure meaningfully
        raise UpstreamUnavailableError(
            f"Embedding failed via provider '{provider.name}': {exc}",
            details={"provider": provider.name},
        ) from exc
    # Handle dimension mismatch gracefully for LMStudio 768 vs DB 384 legacy (truncate/pad + renormalize)
    if len(vector) != s.embedding_dimension:
        got = len(vector)
        exp = s.embedding_dimension
        if got > exp:
            vector = vector[:exp]
        else:
            vector = vector + [0.0] * (exp - got)
        # renormalize after truncate/pad
        import math
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        vector = [round(v / norm, 9) for v in vector]
    return vector
