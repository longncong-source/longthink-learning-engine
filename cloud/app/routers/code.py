"""OpenCode proxy for LongThink — plugin ngam tai :4096, auth required."""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends

from cloud.app.config import get_settings
from cloud.app.security import require_api_key

router = APIRouter(prefix="/v1/code", tags=["code"])

CODE_DEFAULT_URL = "http://127.0.0.1:4096"


@router.get("/health")
def code_health(_: None = Depends(require_api_key)):
    settings = get_settings()
    base = getattr(settings, "code_url", CODE_DEFAULT_URL) or CODE_DEFAULT_URL
    import os as _os
    user = _os.environ.get("OPENCODE_SERVER_USERNAME", "opencode")
    pwd = _os.environ.get("OPENCODE_SERVER_PASSWORD", "")
    auth = (user, pwd) if pwd else None
    try:
        r = httpx.get(f"{base.rstrip('/')}/", timeout=3, follow_redirects=True, auth=auth)
        ok = r.status_code in (200, 401, 302, 307)
        # 200 voi auth dung la online, 401 ma co pwd nghia la van chay
        return {"status": "online" if ok else "degraded", "base": base, "code": r.status_code, "auth": bool(pwd)}
    except Exception as e:
        return {"status": "offline", "base": base, "error": str(e)[:200]}


@router.get("/config")
def code_config(_: None = Depends(require_api_key)):
    import os as _os
    return {
        "url": CODE_DEFAULT_URL,
        "username": _os.environ.get("OPENCODE_SERVER_USERNAME", "opencode"),
        "password": _os.environ.get("OPENCODE_SERVER_PASSWORD", ""),
        "hint": "opencode web --port 4096 --hostname 127.0.0.1 — login Basic Auth",
    }
