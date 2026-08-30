"""Bulk memory import: convert uploaded files into many memories (agent-friendly).

Formats:
    .json / .jsonl - array of objects or one object per line
                     ({title, content, type, importance, confidence, metadata})
    .csv           - header row; requires 'title' and 'content' columns
    .md            - split by markdown headings (# .. ######)
    .txt           - split by blank-line paragraphs

Every item flows through ``upsert_memory`` so redaction + dedupe apply.
"""

from __future__ import annotations

import csv
import io
import json
import re
from typing import Any

from cloud.app.config import get_settings
from cloud.app.errors import PayloadTooLargeError, UnsupportedMediaTypeError, ValidationError
from cloud.app.services.memory_service import upsert_memory
from cloud.app.schemas import MemoryCreate, MemoryType

SUPPORTED_EXTENSIONS = {".json", ".jsonl", ".csv", ".md", ".markdown", ".txt"}
MAX_IMPORT_ITEMS = 1000

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n")


def _truncate(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def _normalize_item(raw: Any, index: int) -> dict[str, Any]:
    """Lenient normalization: invalid items become {"error": ...} so one bad
    row never aborts a whole batch - isolation happens in import_memories()."""
    if not isinstance(raw, dict):
        return {"error": f"item #{index}: expected object"}
    content = raw.get("content")
    if not isinstance(content, str) or not content.strip():
        return {"error": f"item #{index}: missing or empty 'content'"}
    return {
        "title": _truncate(str(raw.get("title") or content.strip()), 300),
        "content": content,
        "type": raw.get("type"),
        "importance": raw.get("importance"),
        "confidence": raw.get("confidence"),
        "metadata": raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {},
    }


def parse_json(text: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"invalid JSON: {exc.msg} (line {exc.lineno})") from exc
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        data = data["items"]
    if not isinstance(data, list):
        raise ValidationError("JSON must be an array of memory objects")
    return [_normalize_item(item, i) for i, item in enumerate(data)]


def parse_jsonl(text: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as exc:
            items.append({"error": f"line {line_no}: invalid JSON ({exc.msg})"})
            continue
        items.append(_normalize_item(parsed, line_no))
    return items


def parse_csv(text: str) -> list[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise ValidationError("CSV has no header row")
    columns = {name.strip().lower(): name for name in reader.fieldnames}
    if "title" not in columns or "content" not in columns:
        raise ValidationError("CSV requires 'title' and 'content' columns")
    items: list[dict[str, Any]] = []
    for row_no, row in enumerate(reader, start=2):
        get = lambda key: (row[columns[key]] or "").strip() if columns.get(key) in row else ""  # noqa: E731
        raw = {
            "title": get("title"),
            "content": get("content"),
            "type": get("type") or None,
            "importance": float(get("importance")) if get("importance") else None,
            "confidence": float(get("confidence")) if get("confidence") else None,
            "metadata": {"row": row_no},
        }
        items.append(_normalize_item(raw, row_no))
    return items


def parse_markdown(text: str) -> list[dict[str, Any]]:
    sections: list[tuple[str | None, str]] = []
    title: str | None = None
    body: list[str] = []
    for line in text.splitlines():
        match = _HEADING.match(line)
        if match:
            if title is not None or any(part.strip() for part in body):
                sections.append((title, "\n".join(body).strip()))
            title = match.group(2).strip()
            body = []
        else:
            body.append(line)
    sections.append((title, "\n".join(body).strip()))

    items: list[dict[str, Any]] = []
    for heading, section_body in sections:
        if not section_body and heading is None:
            continue
        first_line = next((ln.strip() for ln in section_body.splitlines() if ln.strip()), "")
        derived_title = heading or _truncate(first_line, 80)
        if not section_body:
            continue
        items.append({
            "title": derived_title,
            "content": section_body,
            "metadata": {"via": "memory-import"},
        })
    return items


def parse_plaintext(text: str) -> list[dict[str, Any]]:
    paragraphs = [p.strip() for p in _PARAGRAPH_SPLIT.split(text) if p.strip()]
    if not paragraphs:
        return []
    if len(paragraphs) == 1:
        single = paragraphs[0]
        return [{
            "title": _truncate(single, 80),
            "content": single,
            "metadata": {"via": "memory-import"},
        }]
    items = []
    for para in paragraphs:
        sentence = re.split(r"(?<=[.!?…])\s+", para)[0]
        items.append({
            "title": _truncate(sentence or para, 80),
            "content": para,
            "metadata": {"via": "memory-import"},
        })
    return items


def parse_memory_file(filename: str, text: str) -> tuple[str, list[dict[str, Any]]]:
    lower = filename.lower()
    extension = "." + lower.rsplit(".", 1)[-1] if "." in lower else ""
    if extension not in SUPPORTED_EXTENSIONS:
        raise UnsupportedMediaTypeError(
            f"Unsupported import format '{extension}'",
            details={"supported": sorted(SUPPORTED_EXTENSIONS)},
        )
    if extension == ".json":
        return "json", parse_json(text)
    if extension == ".jsonl":
        return "jsonl", parse_jsonl(text)
    if extension == ".csv":
        return "csv", parse_csv(text)
    if extension in {".md", ".markdown"}:
        parsed = parse_markdown(text)
        return ("markdown", parsed if len(parsed) >= 1 else parse_plaintext(text))
    return "text", parse_plaintext(text)


def import_memories(
    filename: str,
    data: bytes,
    project_id: str | None,
    default_type: MemoryType,
    source_override: str | None,
) -> dict[str, Any]:
    """Parse + persist memories from a file. Never raises on per-item errors."""
    settings = get_settings()
    max_bytes = int(settings.max_upload_mb * 1024 * 1024)
    if len(data) > max_bytes:
        raise PayloadTooLargeError(
            f"Import file exceeds {settings.max_upload_mb} MB",
            details={"size_bytes": len(data), "limit_bytes": max_bytes},
        )

    encoding = "utf-8"
    text = data.decode(encoding, errors="replace")
    file_format, parsed = parse_memory_file(filename, text)

    if len(parsed) > MAX_IMPORT_ITEMS:
        raise ValidationError(
            f"Too many items: {len(parsed)} > {MAX_IMPORT_ITEMS}",
            details={"total_parsed": len(parsed), "limit": MAX_IMPORT_ITEMS},
        )

    created = 0
    deduplicated = 0
    redaction_count = 0
    stored_ids: list[str] = []
    errors: list[dict[str, Any]] = []

    for index, item in enumerate(parsed):
        if "error" in item:
            errors.append({"index": index, "error": str(item["error"])[:200]})
            continue
        try:
            payload = MemoryCreate(
                project_id=project_id,
                type=item.get("type") or default_type,
                title=item["title"],
                content=item["content"],
                importance=float(item["importance"]) if item.get("importance") is not None else 0.5,
                confidence=float(item["confidence"]) if item.get("confidence") is not None else 0.8,
                source=source_override or f"file-import:{filename}",
                metadata={**(item.get("metadata") or {}), "import_index": index},
            )
            record, was_dedupe, redactions = upsert_memory(payload)
            created += 1
            deduplicated += int(was_dedupe)
            redaction_count += redactions
            stored_ids.append(str(record.id))
        except Exception as exc:  # noqa: BLE001 - keep importing remaining items
            errors.append({"index": index, "error": str(exc)[:200]})

    return {
        "format": file_format,
        "total_parsed": len(parsed),
        "created": created,
        "deduplicated": deduplicated,
        "redaction_count": redaction_count,
        "memory_ids": stored_ids,
        "errors": errors,
    }
