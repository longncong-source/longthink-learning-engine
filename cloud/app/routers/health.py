"""Health endpoints (spec section 8): /health exact contract + authenticated /health/details."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from cloud.app.config import get_settings
from cloud.app.db import get_repository
from cloud.app.errors import RepositoryError
from cloud.app.security import require_api_key
from cloud.app.textops import isoformat_now

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    """Exact contract from spec: {"status": "ok"}."""
    return {"status": "ok"}


@router.get("/health/details", dependencies=[Depends(require_api_key)])
def health_details() -> dict:
    settings = get_settings()
    repo = get_repository(settings)
    storage: dict = {"backend": repo.backend_name}
    reachable = False
    try:
        reachable = bool(repo.ping())
        if reachable:
            storage["info"] = repo.backend_info()
            counts = {
                "memories": repo.count_memories(),
                "projects": repo.count_projects(),
            }
            try:
                counts["documents"] = repo.count_documents()
                counts["document_chunks"] = repo.count_document_chunks()
                storage["documents_enabled"] = True
            except Exception:  # noqa: BLE001 - older backends without documents
                storage["documents_enabled"] = False
            storage["counts"] = counts
    except Exception as exc:  # noqa: BLE001 - any storage problem => degraded, never crash
        reachable = False
        storage["error"] = str(exc)
    storage["reachable"] = reachable

    return {
        "status": "ok" if reachable else "degraded",
        "environment": settings.environment,
        "storage": storage,
        "embeddings": {
            "provider": settings.embedding_provider,
            "model": settings.embedding_model,
            "dimension": settings.embedding_dimension,
            "base_url": settings.embedding_base_url,
        },
        "time": isoformat_now(),
    }
