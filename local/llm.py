"""Local LLM provider abstraction (spec sections 2/17): Ollama, LM Studio, offline fallback.

Both providers are OpenAI-compatible in practice, but Ollama's native /api/chat is
used when available; LM Studio uses /v1/chat/completions. EchoLLM keeps the whole
agent loop functional on a laptop with no model server running.
"""

from __future__ import annotations

import httpx

from local.config import BrainSettings


class LLMUnavailable(RuntimeError):
    pass


def resolve_base_url(provider: str, explicit: str = "") -> str:
    if explicit.strip():
        return explicit.strip().rstrip("/")
    if provider == "lmstudio":
        return "http://127.0.0.1:1234/v1"
    return "http://127.0.0.1:11434"


def llm_online(settings: BrainSettings) -> bool:
    """Cheap availability probe (2s timeout)."""
    base = settings.resolved_llm_base_url
    path = "/models" if settings.llm_provider == "lmstudio" else "/api/tags"
    try:
        resp = httpx.get(f"{base}{path}", timeout=2.0)
        return resp.status_code == 200
    except httpx.HTTPError:
        return False


class BaseChatLLM:
    online = False

    def complete(self, system: str, user: str) -> str:  # pragma: no cover - interface
        raise NotImplementedError


class OllamaChat(BaseChatLLM):
    online = True

    def __init__(self, model: str, base_url: str, api_key: str = "", timeout: float = 90.0) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def complete(self, system: str, user: str) -> str:
        payload = {
            "model": self.model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "options": {"temperature": 0.2},
        }
        try:
            resp = httpx.post(f"{self.base_url}/api/chat", json=payload, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as exc:
            raise LLMUnavailable(f"Ollama chat failed at {self.base_url}: {exc}") from exc
        content = (data.get("message") or {}).get("content", "")
        return str(content).strip()


class OpenAICompatChat(BaseChatLLM):
    """LM Studio / vLLM / any OpenAI-compatible endpoint."""

    online = True

    def __init__(self, model: str, base_url: str, api_key: str = "", timeout: float = 90.0) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def complete(self, system: str, user: str) -> str:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        payload = {
            "model": self.model,
            "stream": False,
            "temperature": 0.2,
            "max_tokens": 700,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        try:
            resp = httpx.post(
                f"{self.base_url}/chat/completions", json=payload, headers=headers, timeout=self.timeout
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as exc:
            raise LLMUnavailable(f"OpenAI-compatible chat failed at {self.base_url}: {exc}") from exc
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMUnavailable("Malformed chat completion response") from exc
        return str(content).strip()


class EchoLLM(BaseChatLLM):
    """Deterministic extractive fallback so the loop still works fully offline."""

    online = False

    @staticmethod
    def _terms(text: str) -> set[str]:
        import re

        stop = {
            "a", "an", "and", "are", "as", "at", "be", "been", "by", "for", "from",
            "has", "have", "in", "is", "it", "its", "of", "on", "that", "the",
            "this", "to", "was", "were", "what", "when", "where", "which", "who",
            "will", "with", "our", "we", "you", "your", "question",
        }
        words = re.findall(r"\w+", (text or "").lower())
        return {w for w in words if w not in stop}

    def complete(self, system: str, user: str) -> str:
        import re

        lines = [ln.strip() for ln in (user or "").splitlines() if ln.strip()]
        # Evidence lines are formatted like "[1] ..."; the rest is question/task context.
        evidence = [ln for ln in lines if re.match(r"^\[\d+\]", ln)]
        focus_text = "\n".join(ln for ln in lines if not re.match(r"^\[\d+\]", ln))
        keywords = self._terms(focus_text)
        if not keywords and lines:
            keywords = self._terms(lines[0])
            evidence = lines[1:] or lines

        candidates = evidence if evidence else lines
        scored: list[tuple[int, str]] = []
        for sentence in candidates:
            overlap = len(keywords & self._terms(sentence)) if keywords else 0
            if overlap:
                scored.append((overlap, sentence))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        picks = [s for _, s in scored[:3]]
        if not picks:
            return ""
        return "[offline-extractive] " + " ".join(picks)


def get_chat_llm(settings: BrainSettings | None = None) -> BaseChatLLM:
    s = settings or BrainSettings()
    if not llm_online(s):
        return EchoLLM()
    base = s.resolved_llm_base_url
    if s.llm_provider == "lmstudio":
        return OpenAICompatChat(s.llm_model, base, s.llm_api_key, s.llm_timeout_seconds)
    if s.llm_provider == "ollama":
        return OllamaChat(s.llm_model, base, s.llm_api_key, s.llm_timeout_seconds)
    return EchoLLM()
