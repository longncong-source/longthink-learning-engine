"""Voice 2-way: STT/TTS providers mocked (no network), router covered via TestClient."""

from __future__ import annotations

import base64

import pytest

from cloud.tests.conftest import AUTH_HEADERS


@pytest.fixture()
def voice_stubs(monkeypatch):  # type: ignore[no-untyped-def]
    from cloud.app.services import voice_service

    async def fake_synth(text, settings=None, voice=None):
        return b"MP3BYTES:" + text.encode("utf-8")[:20], voice or "vi-VN-HoaiMyNeural"

    monkeypatch.setattr(
        voice_service, "transcribe", lambda audio, fn, s=None: "ứng suất vòng là gì"
    )
    monkeypatch.setattr(voice_service, "synthesize", fake_synth)
    monkeypatch.setattr(
        voice_service,
        "answer_from_longthink",
        lambda q, s=None, pid=None: {
            "answer": "Trả lời mẫu",
            "memories_used": 2,
            "sources": [{"n": 1, "id": "x", "type": "document", "title": "t", "score": 0.5}],
        },
    )
    return voice_service


class TestVoiceServiceErrors:
    def test_transcribe_needs_api_key(self, monkeypatch, tmp_path):  # type: ignore[no-untyped-def]
        from cloud.app.config import Settings
        from cloud.app.errors import UpstreamUnavailableError
        from cloud.app.services import voice_service

        s = Settings(_env_file=None, voice_stt_provider="openai", openai_api_key="")  # type: ignore[call-arg]
        with pytest.raises(UpstreamUnavailableError):
            voice_service.transcribe(b"fake", "mic.webm", s)

    def test_transcribe_local_uses_model(self, monkeypatch):  # type: ignore[no-untyped-def]
        from cloud.app.config import Settings
        from cloud.app.services import voice_service

        class FakeSeg:
            def __init__(self, text):  # type: ignore[no-untyped-def]
                self.text = text

        class FakeModel:
            def __init__(self):  # type: ignore[no-untyped-def]
                self.calls = []

            def transcribe(self, path, language=None, beam_size=None):  # type: ignore[no-untyped-def]
                self.calls.append({"path": path, "language": language})
                return [FakeSeg("xin chào "), FakeSeg("LongThink")], None

        fake = FakeModel()
        monkeypatch.setattr(voice_service, "_load_local_model", lambda *a: fake)
        s = Settings(_env_file=None, voice_stt_provider="local")  # type: ignore[call-arg]
        assert voice_service.transcribe(b"FAKEAUDIO", "mic.webm", s) == "xin chào LongThink"
        assert fake.calls and fake.calls[0]["language"] == s.voice_stt_language

    def test_preseed_platform_skips_wmi(self, monkeypatch):  # type: ignore[no-untyped-def]
        """aiohttp calls platform.system() at import (WMI on Windows); a wedged
        WMI service hangs that forever. Preseed must pin the answer first."""
        import platform

        from cloud.app.services import voice_service

        def _hung():  # type: ignore[no-untyped-def]
            raise AssertionError("WMI must not be touched")

        monkeypatch.setattr(platform, "system", _hung)
        monkeypatch.setattr(platform.system, "__module__", "platform")
        voice_service._preseed_platform_system()
        assert platform.system() == "Windows"

    def test_transcribe_local_needs_package(self, monkeypatch):  # type: ignore[no-untyped-def]
        import sys

        from cloud.app.config import Settings
        from cloud.app.errors import DependencyMissingError
        from cloud.app.services import voice_service

        voice_service._local_models.clear()
        monkeypatch.setitem(sys.modules, "faster_whisper", None)
        s = Settings(_env_file=None, voice_stt_provider="local")  # type: ignore[call-arg]
        with pytest.raises(DependencyMissingError):
            voice_service.transcribe(b"fake", "mic.webm", s)

    def test_synthesize_needs_package(self, monkeypatch):  # type: ignore[no-untyped-def]
        import sys

        from cloud.app.config import get_settings
        from cloud.app.errors import DependencyMissingError
        from cloud.app.services import voice_service

        monkeypatch.setitem(sys.modules, "edge_tts", None)
        with pytest.raises(DependencyMissingError):
            import asyncio

            asyncio.run(voice_service.synthesize("xin chào", get_settings()))

    def test_answer_empty_store(self, client):  # type: ignore[no-untyped-def]
        from cloud.app.services import voice_service

        out = voice_service.answer_from_longthink("câu hỏi không tồn tại xyz123")
        assert out["memories_used"] == 0
        assert "chưa có" in out["answer"]
        assert out["sources"] == []


class TestVoiceRouter:
    def test_voices_list(self, client):  # type: ignore[no-untyped-def]
        resp = client.get("/v1/voice/voices", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert "vi-VN-HoaiMyNeural" in body["voices"]
        assert body["default"]

    def test_voices_requires_auth(self, client):  # type: ignore[no-untyped-def]
        assert client.get("/v1/voice/voices").status_code == 401

    def test_stt(self, client, voice_stubs):  # type: ignore[no-untyped-def]
        files = {"audio": ("mic.webm", b"FAKEAUDIO", "audio/webm")}
        resp = client.post("/v1/voice/stt", files=files, headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["text"] == "ứng suất vòng là gì"

    def test_ask_full_turn(self, client, voice_stubs):  # type: ignore[no-untyped-def]
        files = {"audio": ("mic.webm", b"FAKEAUDIO", "audio/webm")}
        resp = client.post("/v1/voice/ask", files=files, headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["question"] == "ứng suất vòng là gì"
        assert body["answer"] == "Trả lời mẫu"
        assert body["memories_used"] == 2
        assert body["voice"] == "vi-VN-HoaiMyNeural"
        assert base64.b64decode(body["audio_base64"]).startswith(b"MP3BYTES:")

    def test_tts(self, client, voice_stubs):  # type: ignore[no-untyped-def]
        resp = client.post(
            "/v1/voice/tts", data={"text": "xin chào"}, headers=AUTH_HEADERS
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "audio/mpeg"
        assert resp.content.startswith(b"MP3BYTES:")

    def test_oversize_rejected(self, client, monkeypatch):  # type: ignore[no-untyped-def]
        from cloud.app.config import get_settings

        monkeypatch.setenv("VOICE_MAX_AUDIO_MB", "0")
        get_settings.cache_clear()
        files = {"audio": ("mic.webm", b"x" * 16, "audio/webm")}
        resp = client.post("/v1/voice/stt", files=files, headers=AUTH_HEADERS)
        get_settings.cache_clear()
        assert resp.status_code == 413

    def test_upload_is_form_file(self, client):  # type: ignore[no-untyped-def]
        resp = client.post(
            "/v1/voice/stt", data={"audio": "not-a-file"}, headers=AUTH_HEADERS
        )
        assert resp.status_code == 422
