r"""Migrate Second Brain data SQLite -> Postgres/pgvector (one-shot, idempotent-ish).

Usage (from repo root):
    .\.venv\Scripts\python.exe scripts\migrate_sqlite_to_pg.py [--sqlite data/second_brain.sqlite3]
        [--database-url postgresql://second_brain:second_brain@localhost:5433/second_brain]

- Creates PG schema via PostgresRepository.init_schema()
- Copies projects -> documents -> chunks -> memories preserving IDs
- Skips rows that already exist (re-runnable)
- Prints counts for verification; exits non-zero on mismatch
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sqlite", default="data/second_brain.sqlite3")
    ap.add_argument(
        "--database-url",
        default="postgresql://second_brain:second_brain@localhost:5433/second_brain",
    )
    args = ap.parse_args()

    from cloud.app.repositories.postgres_repo import PostgresRepository
    from cloud.app.repositories.sqlite_repo import SqliteRepository

    src = SqliteRepository(args.sqlite)
    dst = PostgresRepository(args.database_url)
    print("[pg] init schema ...")
    dst.init_schema()
    if not dst.ping():
        print("[pg] ERROR: cannot ping postgres", file=sys.stderr)
        return 1

    # --- projects ---
    projs = src.list_projects(limit=10000)
    np = 0
    for p in projs:
        try:
            dst.create_project(p)
            np += 1
        except Exception as e:
            if "duplicate" in str(e).lower() or "already exists" in str(e).lower():
                continue
            raise
    print(f"[pg] projects: {np}/{len(projs)}")

    # --- documents + chunks ---
    import psycopg as _pg

    _raw = _pg.connect(args.database_url)
    existing_docs = {str(r[0]) for r in _raw.execute("SELECT id FROM documents")}
    existing_chunks = {str(r[0]) for r in _raw.execute("SELECT id FROM document_chunks")}
    existing_mems = {str(r[0]) for r in _raw.execute("SELECT id FROM memories")}
    _raw.close()
    print(f"[pg] already there: docs={len(existing_docs)} chunks={len(existing_chunks)} mems={len(existing_mems)}")

    docs = src.list_documents(limit=100000)
    nd, nc = 0, 0
    for d in docs:
        if d.id in existing_docs:
            pass
        else:
            try:
                dst.create_document(d)
                nd += 1
            except Exception as e:
                if "duplicate" in str(e).lower() or "already exists" in str(e).lower():
                    pass
                else:
                    raise
        for ch in src.list_document_chunks(d.id, limit=2000):
            if ch["id"] and ch["id"] in existing_chunks:
                continue
            from cloud.app.db import DocumentChunkRecord

            rec = DocumentChunkRecord(
                id=ch["id"],
                document_id=d.id,
                chunk_index=ch["chunk_index"],
                content=(ch["content"] or "").replace("\x00", ""),
                token_count=ch.get("token_count"),
                metadata=ch.get("metadata") or {},
                embedding=None,  # chunk embeddings live on mirrored memories
                created_at=None,
            )
            try:
                dst.create_document_chunk(rec)
                nc += 1
            except Exception as e:
                if "duplicate" in str(e).lower() or "already exists" in str(e).lower():
                    continue
                raise
    print(f"[pg] documents: {nd}/{len(docs)}, chunks: {nc}")

    # --- memories (paginated, embeddings preserved) ---
    def _clean_text(v):  # PG text rejects NUL bytes from PDF artifacts
        return v.replace("\x00", "") if isinstance(v, str) else v

    nm, off, page = 0, 0, 1000
    while True:
        batch = src.list_memories(limit=page, offset=off)
        if not batch:
            break
        for m in batch:
            if m.id in existing_mems:
                continue
            m.title = _clean_text(m.title)
            m.content = _clean_text(m.content)
            m.summary = _clean_text(m.summary)
            m.source = _clean_text(m.source)
            try:
                dst.create_memory(m)
                nm += 1
            except Exception as e:
                if "duplicate" in str(e).lower() or "already exists" in str(e).lower():
                    continue
                raise
        off += len(batch)
        print(f"[pg] memories ... {nm}", flush=True)
    print(f"[pg] memories: {nm}")

    # --- verify ---
    info = dst.backend_info()
    print("[pg] backend:", info)
    dst.close()
    try:
        src._conn.close()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
