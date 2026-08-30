"""Reverse proxy ODC Studio :3001 -> LongThink :8100/odc/*"""
from __future__ import annotations

import os
from fastapi import Request, Response
import httpx

ODC_URL = os.environ.get("ODC_URL", "http://127.0.0.1:3001")
HOP_BY_HOP = {"connection","keep-alive","proxy-authenticate","proxy-authorization","te","trailers","transfer-encoding","upgrade","content-encoding","content-length"}
BLOCKED = {"x-frame-options","content-security-policy","content-security-policy-report-only"}

async def proxy_request(request: Request, path: str = ""):
    qs = f"?{request.url.query}" if request.url.query else ""
    target = f"{ODC_URL.rstrip('/')}/{path.lstrip('/')}{qs}" if path else f"{ODC_URL.rstrip('/')}/{qs.lstrip('?')}"
    if not path and not request.url.query:
        target = f"{ODC_URL.rstrip('/')}/"
    # Also handle root /odc without path
    if path == "":
        # if original was /odc, ensure trailing /
        if request.url.path.endswith("/odc"):
            target = f"{ODC_URL.rstrip('/')}/"
    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_BY_HOP and k.lower() != "host"}
    body = await request.body() if request.method in ("POST","PUT","PATCH","DELETE") else None
    async with httpx.AsyncClient(follow_redirects=False, timeout=30) as client:
        try:
            resp = await client.request(method=request.method, url=target, headers=headers, content=body)
        except Exception as e:
            return Response(content=f"ODC proxy error: {e}", status_code=502)
    resp_headers = {}
    for k, v in resp.headers.items():
        lk = k.lower()
        if lk in HOP_BY_HOP or lk in BLOCKED:
            continue
        if lk == "location" and "127.0.0.1:3001" in v:
            v = v.replace("http://127.0.0.1:3001", str(request.base_url).rstrip("/") + "/odc")
        resp_headers[k] = v
    resp_headers["X-Frame-Options"] = "ALLOWALL"
    content = resp.content
    ctype = resp.headers.get("content-type","")
    if "text/html" in ctype:
        try:
            text = content.decode("utf-8", errors="ignore")
            # ensure base for relative assets
            if '<head>' in text and '<base' not in text:
                text = text.replace('<head>', '<head><base href="/odc/">', 1)
            content = text.encode("utf-8")
            resp_headers["content-length"] = str(len(content))
        except Exception:
            pass
    return Response(content=content, status_code=resp.status_code, headers=resp_headers, media_type=resp.headers.get("content-type"))
