"""LMStudio router — smart status for LongThink."""
from __future__ import annotations

import subprocess
import pathlib
from fastapi import APIRouter, Depends, HTTPException

from cloud.app.security import require_api_key
from cloud.app.services.lmstudio_service import smart_status, probe_lmstudio

router = APIRouter(prefix="/v1/lmstudio", tags=["lmstudio"])

@router.get("/health")
def lmstudio_health(_: None = Depends(require_api_key)):
    return probe_lmstudio().__dict__

@router.get("/status")
def lmstudio_status(_: None = Depends(require_api_key)):
    return smart_status()

@router.post("/switch")
def lmstudio_switch(provider: str, _: None = Depends(require_api_key)):
    if provider not in ("lmstudio", "ollama", "auto"):
        raise HTTPException(status_code=400, detail="provider must be lmstudio|ollama|auto")
    root = pathlib.Path(__file__).resolve().parents[3]
    script = root / "scripts" / "lmstudio.ps1"
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "switch", "-Provider", provider],
            capture_output=True, text=True, timeout=30, cwd=str(root)
        )
        return {"detail": result.stdout[-500:] if result.stdout else "switched", "provider": provider, "code": result.returncode}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)[:500])
