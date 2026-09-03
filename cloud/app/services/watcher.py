"""Folder watcher: incremental auto-index (VECTOR spec sections 18-19).

Poll-based (stdlib only, no watchdog dependency):
  Folder -> detect change -> hash -> compare -> NEW / MODIFIED / DELETED.

- Fast path: (size, mtime) unchanged => skip hashing (UNCHANGED => DO NOTHING).
- NEW: ingest via document_service.ingest_document (chunk -> embed -> index).
- MODIFIED: delete old document (chunks + mirrored memories) then ingest new.
- DELETED: remove document and its chunks/memories.
- State persisted in data/watch_state.json; watched folders in
  data/watch_folders.json (survives restarts).
- Background thread started from app lifespan; scan also runs on demand
  via POST /v1/documents/watch/scan.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

from cloud.app.config import Settings, get_settings
from cloud.app.db import BaseRepository, get_repository
from cloud.app.services.document_service import delete_document, ingest_document

logger = logging.getLogger(__name__)

SUPPORTED_SUFFIXES = {".pdf", ".docx", ".txt", ".md", ".markdown"}

_lock = threading.Lock()
_thread: threading.Thread | None = None
_stop_event = threading.Event()
_last_scan: dict[str, Any] | None = None


def _data_dir(settings: Settings) -> Path:
    # SQLITE_PATH like data/second_brain.sqlite3 -> data/; PG mode: ./data
    try:
        p = Path(str(settings.sqlite_path))
        d = p.parent if p.suffix else Path("data")
    except Exception:
        d = Path("data")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _folders_file(settings: Settings) -> Path:
    return _data_dir(settings) / "watch_folders.json"


def _state_file(settings: Settings) -> Path:
    return _data_dir(settings) / "watch_state.json"


def _load_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - corrupt state must not kill watcher
        logger.warning("watcher: cannot read %s: %s", path, exc)
    return default


def _save_json(path: Path, payload: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def list_watched(settings: Settings | None = None) -> list[dict[str, Any]]:
    s = settings or get_settings()
    items = _load_json(_folders_file(s), [])
    return items if isinstance(items, list) else []


def register_folder(
    path: str,
    project_id: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Register a folder for watching. Raises ValueError on bad path."""
    s = settings or get_settings()
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_dir():
        raise ValueError(f"Not a directory: {path}")
    items = list_watched(s)
    entry = {"path": str(resolved), "project_id": project_id}
    if all(i.get("path") != entry["path"] for i in items):
        items.append(entry)
        _save_json(_folders_file(s), items)
    ensure_started(s)
    return entry


def unregister_folder(path: str, settings: Settings | None = None) -> bool:
    s = settings or get_settings()
    resolved = str(Path(path).expanduser().resolve())
    items = list_watched(s)
    kept = [i for i in items if i.get("path") != resolved]
    if len(kept) == len(items):
        return False
    _save_json(_folders_file(s), kept)
    return True


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def scan_once(
    settings: Settings | None = None,
    repo: BaseRepository | None = None,
) -> dict[str, Any]:
    """Run one incremental scan over all watched folders. Returns summary."""
    s = settings or get_settings()
    repository = repo or get_repository(s)
    max_bytes = int(min(s.max_upload_mb, s.watch_max_mb) * 1024 * 1024)

    state: dict[str, dict[str, Any]] = _load_json(_state_file(s), {})
    if not isinstance(state, dict):
        state = {}

    summary: dict[str, Any] = {
        "folders": 0,
        "new": 0,
        "modified": 0,
        "deleted": 0,
        "unchanged": 0,
        "skipped": 0,
        "errors": [],
    }

    for folder in list_watched(s):
        root = Path(str(folder.get("path", "")))
        if not root.is_dir():
            summary["errors"].append(f"missing folder: {root}")
            continue
        summary["folders"] += 1
        project_id = folder.get("project_id")
        seen: set[str] = set()

        for fpath in sorted(root.rglob("*")):
            if not fpath.is_file() or fpath.name.startswith("."):
                continue
            if fpath.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            rel = fpath.relative_to(root).as_posix()
            key = f"{root}::{rel}"
            seen.add(key)
            try:
                stat = fpath.stat()
            except OSError as exc:
                summary["errors"].append(f"{rel}: {exc}")
                continue
            if stat.st_size > max_bytes:
                summary["skipped"] += 1
                continue
            prev = state.get(key)
            if prev and prev.get("size") == stat.st_size and prev.get("mtime") == stat.st_mtime:
                summary["unchanged"] += 1  # fast path: DO NOTHING
                continue
            digest = _file_hash(fpath)
            if prev and prev.get("sha256") == digest:
                state[key] = {"sha256": digest, "size": stat.st_size,
                              "mtime": stat.st_mtime, "doc_id": prev.get("doc_id")}
                summary["unchanged"] += 1
                continue

            data = fpath.read_bytes()
            source = f"watch:{root.name}/{rel}"
            try:
                if prev and prev.get("doc_id"):
                    kind = "modified"
                    try:
                        delete_document(str(prev["doc_id"]), repo=repository)
                    except Exception as exc:  # noqa: BLE001 - stale doc_id, re-ingest anyway
                        logger.warning("watcher: stale doc %s: %s", prev.get("doc_id"), exc)
                else:
                    kind = "new"
                result = ingest_document(
                    filename=fpath.name,
                    data=data,
                    project_id=project_id,
                    title=rel[:300],
                    source=source,
                    settings=s,
                    repo=repository,
                )
                state[key] = {"sha256": digest, "size": stat.st_size,
                              "mtime": stat.st_mtime,
                              "doc_id": result["document"]["id"]}
                summary[kind] += 1
            except Exception as exc:  # noqa: BLE001 - one bad file must not stop scan
                summary["errors"].append(f"{rel}: {type(exc).__name__}: {exc}")

        # DELETED: tracked before, gone from disk
        for key in [k for k in state if k.startswith(f"{root}::") and k not in seen]:
            doc_id = state[key].get("doc_id")
            if doc_id:
                try:
                    delete_document(str(doc_id), repo=repository)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("watcher: delete missing %s: %s", doc_id, exc)
            del state[key]
            summary["deleted"] += 1

    _save_json(_state_file(s), state)
    global _last_scan
    _last_scan = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), **summary, "errors": summary["errors"][:10]}
    return summary


def status(settings: Settings | None = None) -> dict[str, Any]:
    s = settings or get_settings()
    return {
        "running": _thread is not None and _thread.is_alive(),
        "poll_seconds": s.watch_poll_seconds,
        "folders": list_watched(s),
        "last_scan": _last_scan,
    }


def _loop(settings: Settings) -> None:
    logger.info("watcher: background loop every %ss", settings.watch_poll_seconds)
    while not _stop_event.wait(timeout=max(10, settings.watch_poll_seconds)):
        try:
            if list_watched(settings):
                scan_once(settings)
        except Exception as exc:  # noqa: BLE001 - loop must survive
            logger.warning("watcher loop error: %s", exc)
    logger.info("watcher: stopped")


def ensure_started(settings: Settings | None = None) -> bool:
    """Start background thread if watched folders exist. Idempotent."""
    global _thread
    s = settings or get_settings()
    with _lock:
        if _thread is not None and _thread.is_alive():
            return True
        if not list_watched(s):
            return False
        _stop_event.clear()
        _thread = threading.Thread(target=_loop, args=(s,), name="watcher", daemon=True)
        _thread.start()
        return True


def stop() -> None:
    global _thread
    _stop_event.set()
    with _lock:
        _thread = None
