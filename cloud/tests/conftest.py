"""Shared test configuration: isolated SQLite backend, hash embeddings, fixed API key."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Default test environment BEFORE any cloud.app import happens.
os_environ_defaults = {
    "ENVIRONMENT": "testing",
    "MEMORY_DB_BACKEND": "sqlite",
    "MEMORY_API_KEYS": "test-key-12345",
    "EMBEDDING_PROVIDER": "hash",
    "EMBEDDING_DIMENSION": "64",
    "EMBEDDING_MODEL": "test-hash-model",
    "RATE_LIMIT_PER_MINUTE": "100000",
}
for key, value in os_environ_defaults.items():
    import os

    os.environ[key] = value

TEST_API_KEY = "test-key-12345"
AUTH_HEADERS = {"X-API-Key": TEST_API_KEY}


def configure_test_env(monkeypatch, tmp_path, **overrides) -> None:  # type: ignore[no-untyped-def]
    values = dict(os_environ_defaults)
    values["SQLITE_PATH"] = str(Path(tmp_path) / f"brain-{id(tmp_path)}.sqlite3")
    values.update({k: str(v) for k, v in overrides.items()})
    for key, value in values.items():
        monkeypatch.setenv(key, value)

    # Metrics are process-global; isolate them per test
    from cloud.app import metrics

    metrics.reset()


@pytest.fixture()
def fresh_stack(monkeypatch, tmp_path):  # type: ignore[no-untyped-def]
    """Reset cached settings/repo/provider and return a freshly built app + TestClient."""
    configure_test_env(monkeypatch, tmp_path)

    from fastapi.testclient import TestClient

    from cloud.app import main as main_module
    from cloud.app.config import get_settings
    from cloud.app.db import reset_repository
    from cloud.app.embeddings import reset_embedding_provider

    get_settings.cache_clear()
    reset_repository()
    reset_embedding_provider()

    # Drop stale module caches so env-dependent singletons rebuild cleanly
    import importlib

    importlib.reload(main_module)
    app = main_module.create_app()
    with TestClient(app) as http:
        yield http

    get_settings.cache_clear()
    reset_repository()
    reset_embedding_provider()


client_fixture = fresh_stack


@pytest.fixture()
def client(fresh_stack):  # alias with conventional name
    return fresh_stack
