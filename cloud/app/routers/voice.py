"""Voice API routes - 2-way speech for LongThink (STT + ask + TTS)."""

from __future__ import annotations

import base64

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from cloud.app.config import get_settings
from cloud.app.errors import PayloadTooLargeError
from cloud.app.security import require_api_key as verify_api_key
from cloud.app.services import voice_service

router = APIRouter(prefix="/v1/voice", tags=["Voice"])


def _check_size(audio: bytes) -> None:
    limit = get_settings().voice_max_audio_mb * 1024 * 1024
    if len(audio) > limit:
        raise PayloadTooLargeError(
            f"Audio too large ({len(audio)} bytes)",
            details={"max_bytes": limit},
        )


class SttResponse(BaseModel):
    text: str
    language: str


class AskResponse(BaseModel):
    question: str
    answer: str
    memories_used: int
    sources: list[dict] = Field(default_factory=list)
    voice: str
    audio_base64: str
    audio_content_type: str = "audio/mpeg"


@router.get("/voices")
async def list_voices(_: str = Depends(verify_api_key)):
    """Curated Vietnamese TTS voices (EdgeTTS, no key needed)."""
    settings = get_settings()
    return {"default": settings.voice_tts_voice, "voices": voice_service.VI_VOICES}


@router.post("/stt", response_model=SttResponse)
async def speech_to_text(
    audio: UploadFile = File(..., description="Mic recording (webm/wav/mp3)"),
    _: str = Depends(verify_api_key),
):
    """Speech-to-text only: audio -> Vietnamese text (Whisper cloud)."""
    raw = await audio.read()
    _check_size(raw)
    settings = get_settings()
    text = voice_service.transcribe(raw, audio.filename or "mic.webm", settings)
    return {"text": text, "language": settings.voice_stt_language}


@router.post("/ask", response_model=AskResponse)
async def voice_ask(
    audio: UploadFile = File(..., description="Mic recording (webm/wav/mp3)"),
    project_id: str | None = Form(None, description="Optional project UUID"),
    voice: str | None = Form(None, description="TTS voice, default vi-VN-HoaiMyNeural"),
    _: str = Depends(verify_api_key),
):
    """Full voice turn: audio -> text -> LongThink answer -> spoken mp3 (base64)."""
    raw = await audio.read()
    _check_size(raw)
    settings = get_settings()
    question = voice_service.transcribe(raw, audio.filename or "mic.webm", settings)
    result = voice_service.answer_from_longthink(question, settings, project_id)
    mp3, used_voice = await voice_service.synthesize(result["answer"], settings, voice)
    return {
        "question": question,
        "answer": result["answer"],
        "memories_used": result["memories_used"],
        "sources": result["sources"],
        "voice": used_voice,
        "audio_base64": base64.b64encode(mp3).decode("ascii"),
        "audio_content_type": "audio/mpeg",
    }


@router.post("/tts")
async def text_to_speech(
    text: str = Form(..., min_length=1, max_length=5000),
    voice: str | None = Form(None),
    _: str = Depends(verify_api_key),
):
    """Text-to-speech only: text -> mp3 audio (EdgeTTS vi)."""
    settings = get_settings()
    mp3, used_voice = await voice_service.synthesize(text, settings, voice)
    return Response(
        content=mp3,
        media_type="audio/mpeg",
        headers={"X-Voice": used_voice},
    )
