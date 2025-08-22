from typing import Any, Dict, List, Optional, Tuple
import base64, io, json
import httpx
from settings import settings
from nd_oauth import get_access_token, refresh_access_token_if_needed

class NDClient:
    def __init__(self):
        self.api = settings.ND_API_BASE.rstrip('/')

    async def _authed(self) -> Dict[str, str]:
        tok = get_access_token()
        if not tok:
            raise RuntimeError("Not authorized with NetDocuments yet. Visit /oauth/start to authorize.")
        return {"Authorization": f"Bearer {tok}"}

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        headers = kwargs.pop("headers", {})
        headers.update(await self._authed())
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.request(method, f"{self.api}{path}", headers=headers, **kwargs)
            if resp.status_code == 401:
                # try a single refresh then retry once
                fresh = await refresh_access_token_if_needed()
                if fresh:
                    headers.update({"Authorization": f"Bearer {fresh}"})
                    resp = await client.request(method, f"{self.api}{path}", headers=headers, **kwargs)
            resp.raise_for_status()
            return resp

    async def get_user_cabinets(self) -> List[Dict[str, Any]]:
        resp = await self._request("GET", "/User/cabinets")
        return resp.json()

    async def search(self, q: str, cabinet_id: Optional[str] = None, top: int = 50, orderby: str = "relevance", select: str = "standardAttributes", skiptoken: Optional[str] = None) -> Dict[str, Any]:
        params = {"$top": str(top), "$orderby": f"{orderby} desc", "$select": select}
        if skiptoken:
            params["$skiptoken"] = skiptoken
        if cabinet_id:
            path = f"/Search/{cabinet_id}"
        else:
            path = "/Search"
        params["q"] = q
        resp = await self._request("GET", path, params=params)
        return resp.json()

    async def get_document_info(self, doc_id: str) -> Dict[str, Any]:
        resp = await self._request("GET", f"/Document/{doc_id}/info")
        return resp.json()

    async def download_document_bytes_base64(self, doc_id: str) -> bytes:
        # Add base64=true to ensure base64-encoded response body (then decode)
        resp = await self._request("GET", f"/Document/{doc_id}", params={"base64":"true"})
        # Some ND implementations return raw bytes; with base64=true we expect base64 text
        b64txt = resp.text
        return base64.b64decode(b64txt)
