"""Unit tests: LocalStore (session notes, pending queue, TTL cache) - spec sections 16/23/24."""

from __future__ import annotations

import time


def test_notes_roundtrip(tmp_path):  # type: ignore[no-untyped-def]
    from local.local_store import LocalStore

    store = LocalStore(tmp_path / "local.db")
    note_id = store.add_note("task", "Working on vendor delay analysis")
    assert note_id
    notes = store.list_notes()
    assert any(n["kind"] == "task" and "vendor delay" in n["content"] for n in notes)
    store.close()


def test_pending_queue_lifecycle(tmp_path):  # type: ignore[no-untyped-def]
    from local.local_store import LocalStore

    store = LocalStore(tmp_path / "local.db")
    assert store.pending_count() == 0

    item_id = store.enqueue_write({"title": "t", "content": "c"})
    assert store.pending_count() == 1

    batch = store.pending_batch(limit=10)
    assert len(batch) == 1 and batch[0]["id"] == item_id
    payload = __import__("json").loads(batch[0]["payload"])
    assert payload == {"title": "t", "content": "c"}

    store.mark_write_done(item_id)
    assert store.pending_count() == 0
    store.close()


def test_failed_write_stays_queued_for_retry(tmp_path):  # type: ignore[no-untyped-def]
    from local.local_store import LocalStore

    store = LocalStore(tmp_path / "local.db")
    item_id = store.enqueue_write({"a": 1})
    store.mark_write_failed(item_id, "connection refused", permanent=False)
    assert store.pending_count() == 1
    row = store.pending_batch()[0]
    assert row["attempts"] == 1
    assert "refused" in row["last_error"]
    store.close()


def test_permanent_failure_drops_and_audits(tmp_path):  # type: ignore[no-untyped-def]
    from local.local_store import LocalStore

    store = LocalStore(tmp_path / "local.db")
    item_id = store.enqueue_write({"a": 1})
    store.mark_write_failed(item_id, "permanent HTTP 422", permanent=True)
    assert store.pending_count() == 0
    notes = store.list_notes()
    assert any(n["kind"] == "dropped_write" for n in notes)
    store.close()


def test_cache_ttl_expiry(tmp_path):  # type: ignore[no-untyped-def]
    import pytest

    pytest.importorskip("sqlite3")  # trivial guard keeps linters happy
    from local.local_store import LocalStore

    store = LocalStore(tmp_path / "local.db")
    store.cache_set("k", {"answer": 42}, ttl_seconds=600)
    assert store.cache_get("k") == {"answer": 42}

    # Force expiry deterministically (fast tests instead of sleeping)
    with store._lock:
        store._conn.execute(
            "UPDATE query_cache SET expires_at=? WHERE cache_key=?", (time.time() - 5, "k")
        )
        store._conn.commit()
    assert store.cache_get("k") is None
    store.close()


def test_cache_isolation_between_keys(tmp_path):  # type: ignore[no-untyped-def]
    from local.local_store import LocalStore

    store = LocalStore(tmp_path / "local.db")
    store.cache_set("a", {"v": 1}, ttl_seconds=60)
    store.cache_set("b", {"v": 2}, ttl_seconds=60)
    assert store.cache_get("a") == {"v": 1}
    assert store.cache_get("b") == {"v": 2}
    cleared = store.clear_cache()
    assert cleared == 2
    store.close()
