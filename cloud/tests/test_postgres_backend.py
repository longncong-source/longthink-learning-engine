"""Integration tests against real PostgreSQL + pgvector.

Auto-skipped unless RUN_PG_TESTS=1 and DATABASE_URL points at a live database.
Run with Docker stack up:
    set RUN_PG_TESTS=1 && set PG_TEST_DATABASE_URL=postgresql://second_brain:second_brain@localhost:5433/second_brain
    python -m pytest cloud/tests/test_postgres_backend.py -m integration -v
"""

from __future__ import annotations

import os
import uuid

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("RUN_PG_TESTS") != "1",
        reason="RUN_PG_TESTS=1 not set (PostgreSQL integration disabled)",
    ),
]

PG_URL = os.environ.get("PG_TEST_DATABASE_URL", "postgresql://second_brain:second_brain@localhost:5433/second_brain")


@pytest.fixture(scope="module")
def pg_repo():
    from cloud.app.repositories.postgres_repo import PostgresRepository

    repo = PostgresRepository(PG_URL)
    repo.init_schema()
    yield repo
    repo.close()


def _record(**over):
    from cloud.app.db import MemoryRecord

    base = {
        "type": "lesson",
        "title": "Vendor review lesson",
        "content": "Engineering document review must start before procurement.",
        "importance": 0.7,
        "confidence": 0.85,
        "metadata": {"source_test": "pytest"},
        "embedding": [0.01] * 384,
    }
    base.update(over)
    return MemoryRecord(**base)


class TestPostgresBackend:
    def test_ping_and_pgvector_available(self, pg_repo):  # type: ignore[no-untyped-def]
        assert pg_repo.ping()
        info = pg_repo.backend_info()
        assert info.get("pgvector") is True, info

    def test_project_crud(self, pg_repo):  # type: ignore[no-untyped-def]
        from cloud.app.db import ProjectRecord

        created = pg_repo.create_project(ProjectRecord(name=f"pg-test-{uuid.uuid4().hex[:8]}"))
        assert created.id
        fetched = pg_repo.get_project(created.id)
        assert fetched is not None and fetched.name == created.name
        assert pg_repo.find_project_by_name(created.name).id == created.id

    def test_memory_crud_and_search(self, pg_repo):  # type: ignore[no-untyped-def]
        record = pg_repo.create_memory(_record())
        assert record.created_at and record.updated_at

        fetched = pg_repo.get_memory(record.id)
        assert fetched.title == record.title

        params = {
            "query": "document review before procurement",
            "query_embedding": [0.01] * 384,
            "top_k": 5,
        }
        from cloud.app.db import SearchParams

        scored = pg_repo.search(
            SearchParams(**params),
            weights={"semantic": 0.6, "keyword": 0.2, "importance": 0.1, "recency": 0.1},
            half_life_days=30,
            candidate_limit=100,
        )
        assert scored, "expected the seeded row to be retrievable"
        assert scored[0].record.id == record.id

        neighbor = pg_repo.nearest_neighbor([0.01] * 384, None, "lesson")
        assert neighbor is not None and neighbor[1] > 0.99

        updated = pg_repo.update_memory(record.id, {"importance": 0.95})
        assert updated.importance == pytest.approx(0.95)

        assert pg_repo.delete_memory(record.id) is True
        assert pg_repo.get_memory(record.id) is None

    def test_vector_distance_ordering(self, pg_repo):  # type: ignore[no-untyped-def]
        near = pg_repo.create_memory(_record(embedding=[1.0] + [0.0] * 383))
        far = pg_repo.create_memory(_record(embedding=[0.0] * 383 + [1.0], title="Far memory"))
        try:
            from cloud.app.db import SearchParams

            scored = pg_repo.search(
                SearchParams(query="lesson", query_embedding=[1.0] + [0.0] * 383, top_k=10),
                weights={"semantic": 1.0, "keyword": 0.0, "importance": 0.0, "recency": 0.0},
                half_life_days=30,
                candidate_limit=100,
            )
            ids = [s.record.id for s in scored]
            assert ids.index(near.id) < ids.index(far.id)
        finally:
            pg_repo.delete_memory(near.id)
            pg_repo.delete_memory(far.id)
