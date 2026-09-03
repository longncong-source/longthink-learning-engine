"""ComfyUI proxy for Second Brain (SHORT-TERM visual cache) — auth required."""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from cloud.app.config import get_settings
from cloud.app.security import require_api_key

router = APIRouter(prefix="/v1/comfy", tags=["comfy"])

COMFY_DEFAULT_URL = "http://127.0.0.1:8188"


class ComfyGenerateRequest(BaseModel):
    prompt: str
    negative: str = ""
    workflow_path: str | None = None
    timeout: float = 600


@router.get("/health")
def comfy_health(_: None = Depends(require_api_key)):
    settings = get_settings()
    base = getattr(settings, "comfy_url", COMFY_DEFAULT_URL) or COMFY_DEFAULT_URL
    try:
        r = httpx.get(f"{base.rstrip('/')}/system_stats", timeout=3)
        return {"status": "online" if r.status_code == 200 else "degraded", "base": base, "code": r.status_code}
    except Exception as e:
        return {"status": "offline", "base": base, "error": str(e)[:200]}


@router.post("/generate")
def comfy_generate(req: ComfyGenerateRequest, _: None = Depends(require_api_key)):
    # proxy to local ComfyUI — keeps auth + audit
    settings = get_settings()
    base = getattr(settings, "comfy_url", COMFY_DEFAULT_URL) or COMFY_DEFAULT_URL
    try:
        # reuse local client logic
        from local.comfy_client import ComfyClient

        client = ComfyClient(base_url=base)
        result = client.generate(
            prompt=req.prompt,
            negative=req.negative,
            workflow_path=req.workflow_path,
            timeout=max(30, min(req.timeout, 900)),
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"ComfyUI error: {e}")
