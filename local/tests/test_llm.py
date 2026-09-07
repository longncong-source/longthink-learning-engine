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
        assert resolve_base_url("deepseek", "") == "https://api.deepseek.com/v1"
        # openclaw has no implicit default: gateway :18790 is WS RPC, not /v1
        assert resolve_base_url("openclaw", "") == ""

    def test_explicit_wins(self):  # type: ignore[no-untyped-def]
        assert resolve_base_url("ollama", "http://gpu-box:11500/") == "http://gpu-box:11500"
        assert resolve_base_url("deepseek", "http://proxy:8080/v1") == "http://proxy:8080/v1"
        assert resolve_base_url("openclaw", "http://proxy:8080/v1/") == "http://proxy:8080/v1"


class TestOpenClawWiring:
    def test_unconfigured_falls_back_to_echo(self, monkeypatch):  # type: ignore[no-untyped-def]
        settings = BrainSettings(
            llm_provider="openclaw",
            llm_model="gpt-4o",
            llm_base_url="",
            llm_api_key="",
            openclaw_base_url="",
            openclaw_api_key="",
        )
        assert settings.resolved_llm_base_url == ""
        assert settings.openclaw_configured is False
        assert settings.openclaw_integration_warning == "" or isinstance(
            settings.openclaw_integration_warning, str
        )
        llm = get_chat_llm(settings)
        assert isinstance(llm, EchoLLM)

    def test_configured_selects_openai_compat(self, monkeypatch):  # type: ignore[no-untyped-def]
        monkeypatch.setattr("local.llm.llm_online", lambda s: True)
        settings = BrainSettings(
            llm_provider="openclaw",
            llm_model="gpt-4o",
            llm_base_url="",
            llm_api_key="",
            openclaw_base_url="http://127.0.0.1:8899/v1",
            openclaw_api_key="sk-openclaw",
        )
        assert settings.openclaw_configured is True
        llm = get_chat_llm(settings)
        assert isinstance(llm, OpenAICompatChat)
        assert llm.base_url == "http://127.0.0.1:8899/v1"
        assert llm.api_key == "sk-openclaw"

    def test_second_brain_openclaw_warns_when_empty(self):  # type: ignore[no-untyped-def]
        settings = BrainSettings(
            second_brain_provider="openclaw",
            llm_base_url="",
            llm_api_key="",
            openclaw_base_url="",
            openclaw_api_key="",
        )
        assert "OPENCLAW_BASE_URL" in settings.openclaw_integration_warning


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

    def test_online_deepseek_selected(self, monkeypatch):  # type: ignore[no-untyped-def]
        monkeypatch.setattr("local.llm.llm_online", lambda s: True)
        settings = BrainSettings(
            llm_provider="deepseek",
            llm_model="deepseek-chat",
            llm_base_url="",
            deepseek_api_key="sk-test",
        )
        llm = get_chat_llm(settings)
        assert isinstance(llm, OpenAICompatChat)
        assert llm.base_url == "https://api.deepseek.com/v1"
        assert llm.api_key == "sk-test"

    def test_deepseek_key_fallback_llm_api_key(self, monkeypatch):  # type: ignore[no-untyped-def]
        monkeypatch.setattr("local.llm.llm_online", lambda s: True)
        settings = BrainSettings(
            llm_provider="deepseek",
            llm_model="deepseek-reasoner",
            llm_base_url="",
            llm_api_key="sk-via-llm",
        )
        llm = get_chat_llm(settings)
        assert isinstance(llm, OpenAICompatChat)
        assert llm.api_key == "sk-via-llm"

    def test_none_provider_returns_echo(self, monkeypatch):  # type: ignore[no-untyped-def]
        monkeypatch.setattr("local.llm.llm_online", lambda s: True)
        settings = BrainSettings(llm_provider="none")
        llm = get_chat_llm(settings)
        assert isinstance(llm, EchoLLM)
