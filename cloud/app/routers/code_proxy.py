"""Reverse proxy for OpenCode Web :4096 -> LongThink :8100/code/* — auto Basic Auth + strip frame blocks."""
from __future__ import annotations

import os
from fastapi import Request, Response
from fastapi.responses import StreamingResponse
import httpx

CODE_URL = "http://127.0.0.1:4096"

# Headers to strip that block iframe / proxy
HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers", "transfer-encoding", "upgrade", "content-encoding", "content-length"}
BLOCKED_RESP_HEADERS = {"x-frame-options", "content-security-policy", "content-security-policy-report-only"}

def _auth():
    u = os.environ.get("OPENCODE_SERVER_USERNAME", "opencode")
    p = os.environ.get("OPENCODE_SERVER_PASSWORD", "")
    return (u, p) if p else None

async def proxy_request(request: Request, path: str = ""):
    # Build target URL
    qs = f"?{request.url.query}" if request.url.query else ""
    target = f"{CODE_URL.rstrip('/')}/{path.lstrip('/')}{qs}" if path else f"{CODE_URL.rstrip('/')}/{qs.lstrip('?')}"
    if not path and not request.url.query:
        target = f"{CODE_URL.rstrip('/')}/"
    # Filter request headers
    headers = {}
    for k, v in request.headers.items():
        lk = k.lower()
        if lk in HOP_BY_HOP or lk == "host":
            continue
        headers[k] = v
    # Ensure auth
    auth = _auth()
    body = await request.body() if request.method in ("POST", "PUT", "PATCH", "DELETE") else None

    async with httpx.AsyncClient(follow_redirects=False, timeout=30) as client:
        try:
            resp = await client.request(
                method=request.method,
                url=target,
                headers=headers,
                content=body,
                auth=auth,
            )
        except Exception as e:
            return Response(content=f"OpenCode proxy error: {e}", status_code=502)

    # Prepare response headers, strip blocking ones
    resp_headers = {}
    for k, v in resp.headers.items():
        lk = k.lower()
        if lk in HOP_BY_HOP or lk in BLOCKED_RESP_HEADERS:
            continue
        # Rewrite Location if redirect points to 4096
        if lk == "location" and "127.0.0.1:4096" in v:
            v = v.replace("http://127.0.0.1:4096", str(request.base_url).rstrip("/") + "/code")
            v = v.replace("https://127.0.0.1:4096", str(request.base_url).rstrip("/") + "/code")
        resp_headers[k] = v
    # Allow embedding
    resp_headers["X-Frame-Options"] = "ALLOWALL"
    # Relax CSP to allow same origin
    # Keep original content-type
    content = resp.content
    ctype = resp.headers.get("content-type", "")
    if "text/html" in ctype:
        try:
            text = content.decode("utf-8", errors="ignore")
            # Always rewrite absolute URLs so iframe at /code/ loads assets correctly (base tag doesn't affect absolute /)
            text = text.replace('href="/', 'href="/code/').replace('src="/', 'src="/code/').replace('content="/', 'content="/code/').replace("href='/", "href='/code/").replace("src='/", "src='/code/")
            if '<head>' in text:
                text = text.replace('<head>', '<head><base href="/code/">', 1)
            # Inject fetch/WebSocket patch so JS fetch("/api/...") goes via /code proxy
            patch = """<script>try{(function(){var _f=window.fetch;window.fetch=function(u,o){try{if(typeof u==='string'&&u.startsWith('/api'))u='/code'+u;else if(u&&u.url&&typeof u.url==='string'&&u.url.startsWith('/api'))u.url='/code'+u.url;}catch(e){}return _f.call(this,u,o)};}catch(e){}</script>"""
            if '</head>' in text:
                text = text.replace('</head>', patch + '</head>', 1)
            else:
                text = patch + text
            content = text.encode("utf-8")
            resp_headers["content-length"] = str(len(content))
        except Exception:
            pass
    return Response(content=content, status_code=resp.status_code, headers=resp_headers, media_type=resp.headers.get("content-type"))
