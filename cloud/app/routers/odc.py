"""ODC Studio health/config — like code.py/lmstudio.py"""
from __future__ import annotations

import os
import httpx
from fastapi import APIRouter

router = APIRouter(prefix="/v1/odc", tags=["odc"])

ODC_URL = os.environ.get("ODC_URL", "http://127.0.0.1:3001")

@router.get("/health")
async def odc_health():
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            r = await c.get(f"{ODC_URL}/health")
            if r.status_code == 200:
                j = r.json()
                return {"status": "online", "base": ODC_URL, "code": 200, "detail": j}
            return {"status": "offline", "base": ODC_URL, "code": r.status_code}
    except Exception as e:
        return {"status": "offline", "base": ODC_URL, "error": str(e)}

@router.get("/config")
async def odc_config():
    return {"base": ODC_URL, "hint": "ODC Studio :3001 visual orchestration RETRIEVE→THINK→STORE"}
