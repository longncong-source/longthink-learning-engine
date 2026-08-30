"""Rate limiting behaviour (spec section 26 - flood handling)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from cloud.tests.conftest import AUTH_HEADERS, TEST_API_KEY, configure_test_env


def _build_client(monkeypatch, tmp_path: Path, limit: int) -> TestClient:
    configure_test_env(monkeypatch, tmp_path, RATE_LIMIT_PER_MINUTE=limit)

    from cloud.app import main as main_module
    from cloud.app.config import get_settings
    from cloud.app.db import get_repository, reset_repository
    from cloud.app.embeddings import reset_embedding_provider

    get_settings.cache_clear()
    reset_repository()
    reset_embedding_provider()
    app = main_module.create_app()
    get_repository().init_schema()  # TestClient without context manager -> no lifespan
    return TestClient(app)


class TestRateLimit:
    def test_beyond_limit_returns_429_with_retry_after(self, tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
        client = _build_client(monkeypatch, tmp_path, limit=3)

        statuses = []
        for _ in range(5):
            resp = client.get("/health/details", headers={"X-API-Key": TEST_API_KEY})
            statuses.append(resp.status_code)

        assert statuses[:3] == [200, 200, 200]
        assert statuses[3] == 429

        limited = client.get("/health/details", headers=AUTH_HEADERS)
        assert limited.status_code == 429
        header_names = {name.lower() for name in limited.headers}
        assert "retry-after" in header_names
        body = limited.json()
        assert body["error"]["code"] == "rate_limited"
        assert "retry_after_seconds" in body["error"]["details"]

    def test_health_endpoint_is_rate_limited_too(self, tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
        client = _build_client(monkeypatch, tmp_path, limit=2)
        codes = [client.get("/health").status_code for _ in range(4)]
        assert codes[:2] == [200, 200]
        assert 429 in codes

    def test_normal_limit_does_not_affect_usage(self, tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
        client = _build_client(monkeypatch, tmp_path, limit=50)
        codes = [client.get("/health").status_code for _ in range(10)]
        assert all(code == 200 for code in codes)
