# app.py
import os
import threading
from typing import Any, Dict, List

import httpx
from fastapi import FastAPI, Request
from starlette.responses import HTMLResponse, RedirectResponse, StreamingResponse, PlainTextResponse

from fastmcp import FastMCP
from settings import settings
from nd_client import NDClient
from nd_oauth import (
    generate_code_verifier,
    code_challenge_from_verifier,
    build_authorize_url,
    exchange_code_for_tokens,
)
from extractors import extract_text_from_bytes


# =========================
# FastMCP server + tools
# =========================

server_instructions = """
NetDocuments connector (MCP) exposing two tools:
- search(query): returns up to SEARCH_DEFAULT_TOP results (id, title, text snippet, url).
  Inline params supported: cabinetId:<id> top:<n> orderby:<relevance|lastMod> select:<standardAttributes>
  Example: "cabinetId:NG-ABCD top:50 orderby:lastMod project alpha pdf"
  Remaining words become NetDocuments 'q' string.
- fetch(id): downloads binary with base64=true, decodes, extracts plaintext (PDF/DOCX/TXT best-effort), returns full text.

Authorize first via /oauth/start. After callback, tokens are saved and tools can call ND.
"""

mcp = FastMCP(name="NetDocuments MCP", instructions=server_instructions)
nd = NDClient()


def _parse_query_params(q: str) -> Dict[str, Any]:
    import shlex
    parts = shlex.split(q or "")
    params: Dict[str, Any] = {"free": []}
    for p in parts:
        if ":" in p:
            k, v = p.split(":", 1)
            params[k.strip()] = v.strip()
        else:
            params["free"].append(p)
    return params


@mcp.tool()
async def search(query: str) -> Dict[str, List[Dict[str, Any]]]:
    """
    Search NetDocuments. Single string argument supports inline parameters:
    'cabinetId:<id> top:<n> orderby:<relevance|lastMod> select:<standardAttributes>'
    The remaining free text becomes the 'q' parameter for NetDocuments.
    Returns objects with: id, title, text (snippet), url.
    """
    p = _parse_query_params(query)
    cabinet_id = p.get("cabinetId")
    top = int(p.get("top", settings.SEARCH_DEFAULT_TOP))
    orderby = p.get("orderby", settings.SEARCH_DEFAULT_ORDER)
    select = p.get("select", "standardAttributes")
    free = " ".join(p.get("free", []))

    # If no cabinet, try the first available
    if not cabinet_id:
        try:
            cabs = await nd.get_user_cabinets()
            if isinstance(cabs, list) and cabs:
                cabinet_id = cabs[0].get("id") or cabs[0].get("cabinetId")
        except Exception:
            cabinet_id = None  # allow cross-cabinet if supported

    try:
        resp = await nd.search(free, cabinet_id=cabinet_id, top=top, orderby=orderby, select=select)
    except Exception as e:
        return {"results": [], "error": str(e)}

    results = []
    items = resp if isinstance(resp, list) else resp.get("results") or resp.get("items") or []
    for i, it in enumerate(items):
        doc_id = it.get("id") or it.get("documentId") or it.get("docId") or it.get("_id") or str(i)
        name = it.get("name") or it.get("title") or it.get("filename") or f"Document {i+1}"
        ext = it.get("extension") or it.get("fileExtension") or ""
        title = f"{name}{('.' + ext) if ext and not name.lower().endswith('.'+ext.lower()) else ''}"
        snippet = it.get("description") or it.get("summary") or "No preview available"
        url = it.get("url") or it.get("href") or ""
        results.append({"id": str(doc_id), "title": title, "text": snippet, "url": url})

    return {"results": results}


@mcp.tool()
async def fetch(id: str) -> Dict[str, Any]:
    """Retrieve full text for a document by ID. Returns id, title, text, url, metadata."""
    try:
        info = await nd.get_document_info(id)
    except Exception as e:
        info = {"name": f"Document {id}", "error": str(e)}

    try:
        data = await nd.download_document_bytes_base64(id)
    except Exception as e:
        return {"id": id, "title": info.get("name") or f"Document {id}", "text": "", "url": "", "metadata": {"error": str(e)}}

    filename = info.get("name") or info.get("filename") or f"document-{id}"
    text, mime = extract_text_from_bytes(filename, data)
    truncated = False
    if text and len(text) > settings.MAX_FETCH_CHARS:
        text = text[: settings.MAX_FETCH_CHARS] + "\n\n[Truncated]"
        truncated = True

    return {
        "id": id,
        "title": filename,
        "text": text or "",
        "url": info.get("url") or "",
        "metadata": {
            "mime": mime,
            "truncated": truncated,
            "cabinetId": info.get("cabinetId"),
            "repositoryId": info.get("repositoryId"),
            "extension": info.get("extension"),
            "size": info.get("size"),
        },
    }


def _start_internal_mcp():
    # Run FastMCP SSE server on 127.0.0.1:<INTERNAL_SSE_PORT>
    mcp.run(transport="sse", host="127.0.0.1", port=settings.INTERNAL_SSE_PORT)


# =========================
# FastAPI app (public)
# =========================

app = FastAPI(title="NetDocuments MCP Unified Server")

# Simple in-memory state for PKCE
_state = None
_verifier = None


@app.on_event("startup")
async def startup_event():
    # Avoid double-start when using --reload
    if getattr(app.state, "mcp_started", False):
        return
    app.state.mcp_started = True
    t = threading.Thread(target=_start_internal_mcp, daemon=True)
    t.start()


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.get("/")
async def root():
    return HTMLResponse(
        """
        <h3>NetDocuments MCP</h3>
        <p><a href="/oauth/start">Authorize with NetDocuments</a></p>
        <p>ChatGPT connector endpoint: <code>/sse/</code></p>
        """
    )


# ----- OAuth endpoints -----

@app.get("/oauth/start")
async def oauth_start():
    import secrets
    global _state, _verifier
    _state = secrets.token_urlsafe(16)
    _verifier = generate_code_verifier()
    challenge = code_challenge_from_verifier(_verifier)
    url = build_authorize_url(_state, challenge)
    return RedirectResponse(url)


@app.get("/oauth/callback")
async def oauth_callback(request: Request, code: str | None = None, state: str | None = None):
    if state != _state:
        return PlainTextResponse("State mismatch", status_code=400)
    if not code:
        return PlainTextResponse("Missing code", status_code=400)

    # If your tenant enforces PKCE verification during token exchange, add code_verifier parameter:
    # tok = await exchange_code_for_tokens(code, _verifier)
    tok = await exchange_code_for_tokens(code)  # works for many tenants; switch to the line above if needed

    return HTMLResponse(
        f"""
        <h3>Authorized!</h3>
        <pre>{tok}</pre>
        <p>Tokens saved. You can now connect ChatGPT to <code>/sse/</code>.</p>
        """
    )


# ----- SSE proxy to internal FastMCP server -----

@app.get("/sse/")
async def sse_proxy(request: Request):
    """
    Reverse-proxy the Server-Sent Events endpoint from the internal FastMCP server
    so that both OAuth and MCP live under one public origin.
    """
    target = f"http://127.0.0.1:{settings.INTERNAL_SSE_PORT}/sse/"
    headers = {
        # Preserve typical SSE headers
        "accept": request.headers.get("accept", "text/event-stream"),
        "cache-control": "no-cache",
        "connection": "keep-alive",
    }

    async def event_stream():
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("GET", target, headers=headers, params=dict(request.query_params)) as r:
                r.raise_for_status()
                async for chunk in r.aiter_raw():
                    # Pass through exact bytes from the SSE origin
                    yield chunk

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# Entry point (local dev)
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.SERVER_HOST, port=settings.SERVER_PORT)
