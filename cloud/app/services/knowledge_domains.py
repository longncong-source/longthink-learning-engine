"""ONE VECTOR PLATFORM status (VECTOR spec section 8).

One physical vector platform, 8 logical knowledge domains. LongThink memory
types map onto domains; explicit metadata.knowledge_type wins over the memory
type so a classified row is counted exactly once:

    PROJECT     <- type=project
    ENGINEERING <- knowledge_type=engineering
    STANDARD    <- knowledge_type=standard
    CONTRACT    <- knowledge_type=contract
    METHOD      <- type=procedural | knowledge_type=method
    SITE        <- knowledge_type=site
    DOCUMENT    <- type=document
    LESSON      <- type=lesson | knowledge_type=lesson
    (unclassified <- everything else: semantic/episodic/decision/task/...)
"""

from __future__ import annotations

from typing import Any

from cloud.app.config import Settings, get_settings
from cloud.app.db import BaseRepository, get_repository

DOMAINS: list[dict[str, Any]] = [
    {"key": "project", "label": "PROJECT", "types": {"project"}, "kts": set()},
    {"key": "engineering", "label": "ENGINEERING", "types": set(), "kts": {"engineering"}},
    {"key": "standard", "label": "STANDARD", "types": set(), "kts": {"standard"}},
    {"key": "contract", "label": "CONTRACT", "types": set(), "kts": {"contract"}},
    {"key": "method", "label": "METHOD", "types": {"procedural"}, "kts": {"method"}},
    {"key": "site", "label": "SITE", "types": set(), "kts": {"site"}},
    {"key": "document", "label": "DOCUMENT", "types": {"document"}, "kts": set()},
    {"key": "lesson", "label": "LESSON", "types": {"lesson"}, "kts": {"lesson"}},
]


def platform_status(
    settings: Settings | None = None,
    repo: BaseRepository | None = None,
) -> dict[str, Any]:
    s = settings or get_settings()
    repository = repo or get_repository(s)
    matrix = repository.memory_type_matrix()

    domains = [{**d, "count": 0, "by_type": {}} for d in DOMAINS]
    unclassified = 0
    unclassified_types: dict[str, int] = {}
    total = 0

    for row in matrix:
        mtype = str(row.get("type") or "")
        kt = row.get("knowledge_type")
        n = int(row.get("count") or 0)
        total += n
        if kt:
            target = next((d for d in domains if kt in d["kts"]), None)
            if target is None:
                unclassified += n
                unclassified_types[f"kt:{kt}"] = unclassified_types.get(f"kt:{kt}", 0) + n
                continue
        else:
            target = next((d for d in domains if mtype in d["types"]), None)
            if target is None:
                unclassified += n
                unclassified_types[mtype] = unclassified_types.get(mtype, 0) + n
                continue
        target["count"] += n
        target["by_type"][mtype] = target["by_type"].get(mtype, 0) + n

    return {
        "backend": repository.backend_name,
        "embedding_dimension": s.embedding_dimension,
        "total_memories": total,
        "domains": [
            {
                "key": d["key"],
                "label": d["label"],
                "count": d["count"],
                "status": "active" if d["count"] > 0 else "empty",
                "memory_types": d["by_type"],
            }
            for d in domains
        ],
        "unclassified": {"count": unclassified, "memory_types": unclassified_types},
    }


__all__ = ["DOMAINS", "platform_status"]
