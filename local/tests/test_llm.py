"""Unit tests: LLM provider abstraction (spec section 2)."""

from __future__ import annotations

import httpx
import pytest

from local.config import BrainSettings
from local.llm import (
    EchoLLM,
    LLMUnavailable,
    OllamaChat,
    OpenAICompatChat,
    get_chat_llm,
    resolve_base_url,
)


class TestResolveBaseUrl:
    def test_defaults(self):  # type: ignore[no-untyped-def]
        assert resolve_base_url("ollama", "") == "http://127.0.0.1:11434"
        assert resolve_base_url("lmstudio", "").endswith("/v1")

    def test_explicit_wins(self):  # type: ignore[no-untyped-def]
        assert resolve_base_url("ollama", "http://gpu-box:11500/") == "http://gpu-box:11500"


class TestEchoLLM:
    def test_extractive_fallback_picks_relevant_sentences(self):  # type: ignore[no-untyped-def]
        llm = EchoLLM()
        user = (
            "Question: what happened with mechanical delays?\n"
            "[1] Vendor A delayed mechanical drawing approval by 21 days.\n"
            "[2] The office pizza party is on Friday.\n"
        )
        out = llm.complete("system", user)
        assert "mechanical" in out.lower()
        assert "pizza" not in out.lower()


class TestOllamaChat:
    def test_success(self, monkeypatch):  # type: ignore[no-untyped-def]
        captured = {}

        def fake_post(url, json=None, timeout=None, **kw):
            captured["url"] = url
            captured["payload"] = json
            request = httpx.Request("POST", url)
            return httpx.Response(200, json={"message": {"content": " answer "}}, request=request)

        monkeypatch.setattr("local.llm.httpx.post", fake_post)
        llm = OllamaChat("llama3.2", "http://127.0.0.1:11434")
        assert llm.complete("sys", "usr") == "answer"
        assert captured["url"].endswith("/api/chat")
        assert captured["payload"]["model"] == "llama3.2"

    def test_failure_raises_unavailable(self, monkeypatch):  # type: ignore[no-untyped-def]
        def boom(url, **kw):
            raise httpx.ConnectError("refused")

        monkeypatch.setattr("local.llm.httpx.post", boom)
        with pytest.raises(LLMUnavailable):
            OllamaChat("m", "http://127.0.0.1:1").complete("s", "u")


class TestOpenAICompatChat:
    def test_success_lmstudio_shape(self, monkeypatch):  # type: ignore[no-untyped-def]
        def fake_post(url, json=None, headers=None, timeout=None, **kw):
            request = httpx.Request("POST", url)
            payload = {
                "choices": [{"message": {"content": "hello from lm studio"}}]
            }
            return httpx.Response(200, json=payload, request=request)

        monkeypatch.setattr("local.llm.httpx.post", fake_post)
        llm = OpenAICompatChat("qwen", "http://127.0.0.1:1234/v1")
        out = llm.complete("sys", "usr")
        assert out == "hello from lm studio"

    def test_malformed_payload_raises(self, monkeypatch):  # type: ignore[no-untyped-def]
        def fake_post(url, **kw):
            request = httpx.Request("POST", url)
            return httpx.Response(200, json={"weird": True}, request=request)

        monkeypatch.setattr("local.llm.httpx.post", fake_post)
        with pytest.raises(LLMUnavailable):
            OpenAICompatChat("qwen", "http://127.0.0.1:1234/v1").complete("s", "u")


class TestFactoryFallback:
    def test_offline_returns_echo(self, monkeypatch):  # type: ignore[no-untyped-def]
        monkeypatch.setattr("local.llm.llm_online", lambda s: False)
        settings = BrainSettings(llm_provider="ollama")
        llm = get_chat_llm(settings)
        assert isinstance(llm, EchoLLM)
        assert llm.online is False

    def test_online_ollama_selected(self, monkeypatch):  # type: ignore[no-untyped-def]
        monkeypatch.setattr("local.llm.llm_online", lambda s: True)
        settings = BrainSettings(llm_provider="ollama", llm_model="llama3.2")
        llm = get_chat_llm(settings)
        assert isinstance(llm, OllamaChat)
