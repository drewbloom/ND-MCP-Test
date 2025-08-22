import asyncio
from typing import Any, Dict, List
from fastmcp import FastMCP
from settings import settings
from nd_client import NDClient
from extractors import extract_text_from_bytes
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

server_instructions = """
NetDocuments connector (MCP) exposing two tools:
- search(query): returns up to SEARCH_DEFAULT_TOP results (id, title, text snippet, url).
  You may include lightweight parameters inline in the query string using a mini-language:
    cabinetId:<id> top:<n> orderby:<relevance|lastMod> select:<standardAttributes>
  Example: "cabinetId:NG-ABCD1234 top:50 orderby:lastMod project alpha pdf"
  Anything not matching key:value is treated as free-text and passed to NetDocuments 'q='.
- fetch(id): downloads the binary, extracts plaintext (PDF/DOCX/TXT best-effort), and returns full text.

NOTE: This server uses Authorization Code OAuth (PKCE) against NetDocuments. Before use,
visit /oauth/start (see oauth_runner.py) to sign in and store tokens.
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
    """Search NetDocuments. Single string argument supports inline parameters:
    'cabinetId:<id> top:<n> orderby:<relevance|lastMod> select:<standardAttributes>'
    The remaining free text becomes the 'q' parameter for NetDocuments.
    Returns objects with: id, title, text (snippet), url.
    """
    logger.info(f'Searching NetDocuments for "{query}"...')

    p = _parse_query_params(query)
    cabinet_id = p.get("cabinetId")
    top = int(p.get("top", settings.SEARCH_DEFAULT_TOP))
    orderby = p.get("orderby", settings.SEARCH_DEFAULT_ORDER)
    select = p.get("select", "standardAttributes")
    free = " ".join(p.get("free", []))

    # If no cabinet given, try first available cabinet for the user (MVP behavior).
    if not cabinet_id:
        try:
            cabs = await nd.get_user_cabinets()
            if isinstance(cabs, list) and cabs:
                cabinet_id = cabs[0].get("id") or cabs[0].get("cabinetId")
        except Exception:
            cabinet_id = None  # allow cross-cabinet if ND supports it

    try:
        resp = await nd.search(free, cabinet_id=cabinet_id, top=top, orderby=orderby, select=select)
    except Exception as e:
        return {"results": [], "error": str(e)}

    results = []
    items = resp if isinstance(resp, list) else resp.get("results") or resp.get("items") or []
    # Fallback: some ND responses may return {items:[...]} or just list
    for i, it in enumerate(items):
        # Heuristics: find id and title/name; standardAttributes often includes name, extension
        doc_id = it.get("id") or it.get("documentId") or it.get("docId") or it.get("_id") or str(i)
        name = it.get("name") or it.get("title") or it.get("filename") or f"Document {i+1}"
        ext = it.get("extension") or it.get("fileExtension") or ""
        title = f"{name}{('.' + ext) if ext and not name.lower().endswith('.'+ext.lower()) else ''}"
        snippet = it.get("description") or it.get("summary") or "No preview available"
        url = it.get("url") or it.get("href") or ""
        results.append({"id": str(doc_id), "title": title, "text": snippet, "url": url})

    logger.info(f'Search results for query "{query}": {results}')

    return {"results": results}

@mcp.tool()
async def fetch(id: str) -> Dict[str, Any]:
    """Retrieve full text for a document by ID. Returns id, title, text, url, metadata."""
    try:
        logger.info(f'Retrieving document for id: {id}')
        info = await nd.get_document_info(id)
    except Exception as e:
        info = {"name": f"Document {id}", "error": str(e)}

    try:
        data = await nd.download_document_bytes_base64(id)
    except Exception as e:
        return {"id": id, "title": info.get("name") or f"Document {id}", "text": "", "url": "", "metadata": {"error": str(e)}}

    filename = info.get("name") or info.get("filename") or f"document-{id}"
    logger.info(f'File located: {filename}')
    text, mime = extract_text_from_bytes(filename, data)
    if text and len(text) > settings.MAX_FETCH_CHARS:
        text = text[: settings.MAX_FETCH_CHARS] + "\n\n[Truncated]"
        truncated = True
    else:
        truncated = False

    result = {
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
    logger.info(f'Full file result for id: {id}:\n{result}')
    return result

def main():
    mcp.run(transport="sse", host=settings.SERVER_HOST, port=settings.SERVER_PORT)

if __name__ == "__main__":
    main()

