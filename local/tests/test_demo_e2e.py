"""Full-stack demo test: real Memory API served by uvicorn on a loopback port.

Proves spec section 27 end-to-end without any external service:
    Local -> Cloud Memory -> Local -> Store decision -> Retrieve it back.
"""

from __future__ import annotations

import socket
import threading
import time

import httpx
import pytest


def _free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


@pytest.fixture()
def live_stack(monkeypatch, tmp_path):  # type: ignore[no-untyped-def]
    """Fresh API app served by a real uvicorn thread + wired SecondBrainClient."""
    from cloud.tests.conftest import TEST_API_KEY, configure_test_env

    configure_test_env(monkeypatch, tmp_path)

    import uvicorn

    from cloud.app import main as main_module
    from cloud.app.config import get_settings
    from cloud.app.db import get_repository, reset_repository
    from cloud.app.embeddings import reset_embedding_provider

    get_settings.cache_clear()
    reset_repository()
    reset_embedding_provider()

    app = main_module.create_app()
    get_repository().init_schema()

    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    base_url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 20
    ready = False
    while time.time() < deadline:
        try:
            if httpx.get(f"{base_url}/health", timeout=1.0).status_code == 200:
                ready = True
                break
        except httpx.HTTPError:
            time.sleep(0.15)
    if not ready:  # pragma: no cover
        server.should_exit = True
        thread.join(timeout=5)
        raise RuntimeError("test uvicorn server did not become ready")

    from local.config import BrainSettings
    from local.local_store import LocalStore
    from local.memory_client import SecondBrainClient

    settings = BrainSettings(
        second_brain_url=base_url,
        second_brain_api_key=TEST_API_KEY,
        data_policy="selective",
        cache_ttl_seconds=60,
        request_timeout_seconds=10.0,
        local_data_dir=str(tmp_path / "local_data"),
    )
    client = SecondBrainClient(
        settings=settings,
        store=LocalStore(settings.local_data_dir + "/local.db"),
    )
    try:
        yield client
    finally:
        server.should_exit = True
        thread.join(timeout=8)
        get_settings.cache_clear()
        reset_repository()
        reset_embedding_provider()


class TestDemoEndToEnd:
    def test_full_loop_passes(self, live_stack, capsys):  # type: ignore[no-untyped-def]
        from local.demo import (
            DEFAULT_DECISION,
            LESSON_REVIEW_FIRST,
            MEMORY_VENDOR_DELAY,
            QUESTION_1,
            run_demo,
        )
        from local.llm import EchoLLM

        exit_code = run_demo(client=live_stack, llm=EchoLLM(), auto_yes=True)
        out = capsys.readouterr().out

        assert exit_code == 0, out
        assert "[PASS]" in out
        assert "LNG Project" in out
        assert MEMORY_VENDOR_DELAY[:40] in out
        assert LESSON_REVIEW_FIRST[:40] in out
        assert QUESTION_1 in out
        assert "14 days" in out.lower()
        assert DEFAULT_DECISION[:30] in out

    def test_demo_idempotent_second_run(self, live_stack, capsys):  # type: ignore[no-untyped-def]
        from local.demo import run_demo
        from local.llm import EchoLLM

        first = run_demo(client=live_stack, llm=EchoLLM(), auto_yes=True)
        second = run_demo(client=live_stack, llm=EchoLLM(), auto_yes=True)
        capsys.readouterr()
        assert first == 0
        assert second == 0  # dedupe merges instead of duplicating/failing
