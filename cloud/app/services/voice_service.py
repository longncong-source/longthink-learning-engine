"""Voice service - 2-way speech for LongThink.

Pipeline: mic audio (webm) -> transcribe -> answer_from_longthink
  (reuse hybrid memory search, cited extractive) -> synthesize
  (EdgeTTS vi-VN, mp3) -> browser playback.

STT providers: local (faster-whisper offline, free, default) |
  openai (Whisper cloud, needs OPENAI_API_KEY).
Audio bytes are never logged or persisted (same rule as query/bodies).
"""

from __future__ import annotations

import httpx

from cloud.app.config import Settings, get_settings
from cloud.app.errors import DependencyMissingError, UpstreamUnavailableError
from cloud.app.schemas import SearchRequest

WHISPER_URL = "https://api.openai.com/v1/audio/transcriptions"

# Curated Vietnamese voices (EdgeTTS, no API key needed).
VI_VOICES: dict[str, str] = {
    "vi-VN-HoaiMyNeural": "Nu - Hoai My",
    "vi-VN-NamMinhNeural": "Nam - Nam Minh",
}

DEFAULT_VOICE = "vi-VN-HoaiMyNeural"


def transcribe(audio: bytes, filename: str, settings: Settings | None = None) -> str:
    """Speech-to-text. Returns plain Vietnamese text."""
    s = settings or get_settings()
    if (s.voice_stt_provider or "local").lower() == "local":
        return _transcribe_local(audio, filename, s)
    if not s.openai_api_key:
        raise UpstreamUnavailableError(
            "Voice STT needs OPENAI_API_KEY (cloud path) or VOICE_STT_PROVIDER=local "
            "(faster-whisper offline, free). Set one in cloud/.env to enable /v1/voice/*."
        )
    try:
        resp = httpx.post(
            WHISPER_URL,
            headers={"Authorization": f"Bearer {s.openai_api_key}"},
            files={"file": (filename or "mic.webm", audio, "audio/webm")},
            data={"model": s.voice_stt_model, "language": s.voice_stt_language},
            timeout=120.0,
        )
        resp.raise_for_status()
        text = (resp.json().get("text") or "").strip()
    except UpstreamUnavailableError:
        raise
    except Exception as exc:  # noqa: BLE001 - surface as 503 with reason
        raise UpstreamUnavailableError(
            "Voice STT failed", details={"reason": str(exc)[:200]}
        ) from exc
    if not text:
        raise UpstreamUnavailableError(
            "Voice STT returned empty text", details={"reason": "empty transcript"}
        )
    return text


_local_models: dict[tuple[str, str, str], object] = {}


def _load_local_model(model_name: str, device: str, compute: str) -> object:
    """Lazy singleton: download once (~500MB for small), reuse across requests."""
    key = (model_name, device, compute)
    if key not in _local_models:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise DependencyMissingError(
                "Voice STT local needs the 'faster-whisper' package. "
                "Install: .venv\\Scripts\\python.exe -m pip install faster-whisper"
            ) from exc
        _local_models[key] = WhisperModel(model_name, device=device, compute_type=compute)
    return _local_models[key]


def _transcribe_local(audio: bytes, filename: str, s: Settings) -> str:
    """Speech-to-text offline via faster-whisper (free, audio never leaves the box)."""
    import os
    import tempfile

    model = _load_local_model(s.voice_stt_model_local, s.voice_stt_device, s.voice_stt_compute)
    suffix = ".webm"
    if filename and "." in filename:
        suffix = "." + filename.rsplit(".", 1)[1].lower()[:5]
    fd_path = ""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(audio)
            fd_path = tmp.name
        segments, _info = model.transcribe(fd_path, language=s.voice_stt_language, beam_size=5)  # type: ignore[attr-defined]
        text = "".join(seg.text for seg in segments).strip()
    except (DependencyMissingError, UpstreamUnavailableError):
        raise
    except Exception as exc:  # noqa: BLE001 - surface as 503 with reason
        raise UpstreamUnavailableError(
            "Voice STT local failed", details={"reason": str(exc)[:200]}
        ) from exc
    finally:
        try:
            if fd_path:
                os.unlink(fd_path)
        except OSError:
            pass
    if not text:
        raise UpstreamUnavailableError(
            "Voice STT local returned empty text", details={"reason": "empty transcript"}
        )
    return text


async def synthesize(
    text: str, settings: Settings | None = None, voice: str | None = None
) -> tuple[bytes, str]:
    """Text-to-speech via EdgeTTS. Returns (mp3 bytes, voice used)."""
    s = settings or get_settings()
    use_voice = voice or s.voice_tts_voice
    if use_voice not in VI_VOICES:
        use_voice = DEFAULT_VOICE
    try:
        import edge_tts  # type: ignore[import-not-found]
    except ImportError as exc:
        raise DependencyMissingError(
            "Voice TTS needs the 'edge-tts' package. "
            "Install: .venv\\Scripts\\python.exe -m pip install edge-tts"
        ) from exc
    clipped = text[: s.voice_max_answer_chars]
    last_exc: Exception | None = None
    for _attempt in range(2):  # 1 retry: Edge endpoint thỉnh thoảng reset kết nối đầu
        try:
            communicate = edge_tts.Communicate(clipped, use_voice)
            chunks = []
            async for piece in communicate.stream():
                if piece.get("type") == "audio" and piece.get("data"):
                    chunks.append(piece["data"])
            last_exc = None
            break
        except Exception as exc:  # noqa: BLE001 - retry once, then surface as 503
            last_exc = exc
    if last_exc is not None:
        raise UpstreamUnavailableError(
            "Voice TTS failed", details={"reason": str(last_exc)[:200]}
        ) from last_exc
    audio = b"".join(chunks)
    if not audio:
        raise UpstreamUnavailableError(
            "Voice TTS returned empty audio", details={"reason": "empty audio"}
        )
    return audio, use_voice


def answer_from_longthink(
    question: str,
    settings: Settings | None = None,
    project_id: str | None = None,
) -> dict:
    """Ask LongThink with plain text: hybrid search -> cited extractive answer.

    Same evidence style as the First Brain offline-extractive path, so spoken
    answers always trace back to real stored content.
    """
    from cloud.app.services import memory_service  # deferred: avoid import cycle

    s = settings or get_settings()
    payload = SearchRequest(query=question, top_k=5)
    if project_id:
        from uuid import UUID

        payload.project_id = UUID(project_id)
    result = memory_service.search_memories(payload, settings=s)
    if not result.results:
        return {
            "answer": "LongThink chưa có nội dung nào liên quan đến câu hỏi này.",
            "memories_used": 0,
            "sources": [],
        }
    parts: list[str] = []
    sources: list[dict] = []
    for i, item in enumerate(result.results[:3], start=1):
        snippet = (item.content or item.summary or item.title or "")[:400]
        parts.append(f"[{i}] {snippet}")
        sources.append({
            "n": i,
            "id": str(item.id),
            "type": str(item.type),
            "title": item.title,
            "score": item.score,
        })
    answer = "Theo nội dung đã lưu trong LongThink: " + " ".join(parts)
    return {"answer": answer, "memories_used": len(result.results), "sources": sources}
