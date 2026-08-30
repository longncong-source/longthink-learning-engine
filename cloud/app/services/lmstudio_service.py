"""LMStudio service — thông minh nhất cho LongThink (auto-detect, health, fallback, optimize)."""
from __future__ import annotations

import httpx
from dataclasses import dataclass

LMSTUDIO_BASE = "http://127.0.0.1:1234/v1"
OLLAMA_BASE = "http://127.0.0.1:11434"

# Model mapping tối ưu
LMSTUDIO_LLM = "vistral-7b-chat"
LMSTUDIO_EMBED = "text-embedding-nomic-embed-text-v1.5"
OLLAMA_LLM = "gemma4:12b"
OLLAMA_EMBED = "nomic-embed-text"

@dataclass
class LMStudioStatus:
    available: bool
    base: str
    models: list[str]
    llm_ready: bool
    embed_ready: bool
    latency_ms: int = 0
    error: str = ""

def probe_lmstudio(timeout: float = 3.0) -> LMStudioStatus:
    import time
    start = time.perf_counter()
    try:
        r = httpx.get(f"{LMSTUDIO_BASE}/models", timeout=timeout)
        r.raise_for_status()
        data = r.json()
        models = [m.get("id", "") for m in data.get("data", [])]
        elapsed = int((time.perf_counter() - start) * 1000)
        return LMStudioStatus(
            available=True,
            base=LMSTUDIO_BASE,
            models=models,
            llm_ready=LMSTUDIO_LLM in models,
            embed_ready=LMSTUDIO_EMBED in models,
            latency_ms=elapsed,
        )
    except Exception as e:
        return LMStudioStatus(available=False, base=LMSTUDIO_BASE, models=[], llm_ready=False, embed_ready=False, error=str(e)[:300])

def probe_ollama(timeout: float = 2.0) -> dict:
    try:
        r = httpx.get(f"{OLLAMA_BASE}/api/tags", timeout=timeout)
        r.raise_for_status()
        models = [m.get("name", "") for m in r.json().get("models", [])]
        return {"available": True, "models": models}
    except Exception as e:
        return {"available": False, "models": [], "error": str(e)[:200]}

def smart_status() -> dict:
    lm = probe_lmstudio()
    ol = probe_ollama()
    # Smart priority: LMStudio (local, mạnh) > Ollama > offline
    if lm.available and lm.llm_ready and lm.embed_ready:
        mode = "lmstudio"
        recommendation = "LMStudio tối ưu — dùng vistral + nomic 768d"
    elif lm.available:
        mode = "lmstudio_partial"
        recommendation = f"LMStudio thiếu model (cần {LMSTUDIO_LLM}, {LMSTUDIO_EMBED})"
    elif ol["available"]:
        mode = "ollama"
        recommendation = "Ollama sẵn sàng"
    else:
        mode = "offline"
        recommendation = "Offline — dùng hash fallback"
    return {
        "mode": mode,
        "lmstudio": lm.__dict__,
        "ollama": ol,
        "recommendation": recommendation,
    }

def chat_via_lmstudio(system: str, user: str, model: str = LMSTUDIO_LLM, timeout: float = 90.0) -> str:
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.2,
        "max_tokens": 800,
        "stream": False,
    }
    r = httpx.post(f"{LMSTUDIO_BASE}/chat/completions", json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()
