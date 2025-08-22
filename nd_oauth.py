import base64, hashlib, os, time
from typing import Dict, Optional
import httpx
from settings import settings

# Very simple in-memory token store for MVP; replace with persistent storage as needed.
TOKENS_PATH = "tokens.json"
_TOKENS: Dict[str, str] = {}

def _load_tokens():
    global _TOKENS
    try:
        import json, os
        if os.path.exists(TOKENS_PATH):
            with open(TOKENS_PATH, "r") as f:
                _TOKENS = json.load(f)
        else:
            _TOKENS = {}
    except Exception:
        _TOKENS = {}

def _save_tokens():
    import json
    with open(TOKENS_PATH, "w") as f:
        json.dump(_TOKENS, f, indent=2)

def get_access_token() -> Optional[str]:
    """Return the current access token if present (MVP: single-user)."""
    _load_tokens()
    return _TOKENS.get("access_token")

def get_refresh_token() -> Optional[str]:
    _load_tokens()
    return _TOKENS.get("refresh_token")

def set_tokens(access_token: str, refresh_token: Optional[str] = None, expires_in: Optional[int] = None):
    _load_tokens()
    _TOKENS["access_token"] = access_token
    if refresh_token:
        _TOKENS["refresh_token"] = refresh_token
    if expires_in:
        _TOKENS["expires_at"] = int(time.time()) + int(expires_in)
    _save_tokens()

# ===== PKCE helpers =====
def generate_code_verifier() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip("=")

def code_challenge_from_verifier(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")

def build_authorize_url(state: str, code_challenge: str) -> str:
    from urllib.parse import urlencode
    params = {
        "client_id": settings.ND_CLIENT_ID,
        "scope": settings.ND_OAUTH_SCOPE,
        "response_type": "code",
        "redirect_uri": settings.ND_REDIRECT_URI,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{settings.ND_AUTH_AUTHORIZE_URL}?{urlencode(params)}"

async def exchange_code_for_tokens(code: str) -> Dict:
    """Exchange auth code for access+refresh tokens."""
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.ND_REDIRECT_URI,
    }
    # ND allows Basic auth with client_id:client_secret for code exchange
    basic = base64.b64encode(f"{settings.ND_CLIENT_ID}:{settings.ND_CLIENT_SECRET}".encode()).decode()
    headers = {"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(settings.ND_AUTH_TOKEN_URL, data=data, headers=headers)
        resp.raise_for_status()
        tok = resp.json()
    set_tokens(tok.get("access_token"), tok.get("refresh_token"), tok.get("expires_in"))
    return tok

async def refresh_access_token_if_needed() -> Optional[str]:
    """Refresh on 401 or when expired (lazy). Returns fresh access token or None."""
    refresh = get_refresh_token()
    if not refresh:
        return None
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh,
    }
    # refresh uses Basic auth header like auth code exchange
    basic = base64.b64encode(f"{settings.ND_CLIENT_ID}:{settings.ND_CLIENT_SECRET}".encode()).decode()
    headers = {"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(settings.ND_AUTH_TOKEN_URL, data=data, headers=headers)
        resp.raise_for_status()
        tok = resp.json()
    set_tokens(tok.get("access_token"), tok.get("refresh_token"), tok.get("expires_in"))
    return tok.get("access_token")
