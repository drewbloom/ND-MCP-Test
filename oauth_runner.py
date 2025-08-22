# A tiny FastAPI app to complete the OAuth handshake and persist tokens for the MCP server.
# Run this once to authorize, then start app.py for the MCP SSE server.
import uvicorn, secrets
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, HTMLResponse, PlainTextResponse
from urllib.parse import urlencode
from nd_oauth import generate_code_verifier, code_challenge_from_verifier, build_authorize_url, exchange_code_for_tokens, set_tokens
from settings import settings

app = FastAPI(title="NetDocuments OAuth Helper")
_state = None
_verifier = None

@app.get("/")
async def root():
    return HTMLResponse("""
    <h3>NetDocuments OAuth Helper</h3>
    <p>Start the OAuth flow: <a href="/oauth/start">/oauth/start</a></p>
    <p>After success, tokens are saved to <code>tokens.json</code>. Then run <code>python app.py</code>.</p>
    """)

@app.get("/oauth/start")
async def oauth_start():
    global _state, _verifier
    _state = secrets.token_urlsafe(16)
    _verifier = generate_code_verifier()
    challenge = code_challenge_from_verifier(_verifier)
    url = build_authorize_url(_state, challenge)
    return RedirectResponse(url)

@app.get("/oauth/callback")
async def oauth_callback(request: Request, code: str = None, state: str = None):
    # For PKCE, ND returns code; state echoes; verifier is held server-side for proof (ND may not require code_verifier on token exchange; if needed, add it).
    if state != _state:
        return PlainTextResponse("State mismatch", status_code=400)
    if not code:
        return PlainTextResponse("Missing code", status_code=400)
    tok = await exchange_code_for_tokens(code)
    return HTMLResponse(f"""
        <h3>Authorized!</h3>
        <pre>{tok}</pre>
        <p>Tokens saved. You can close this tab and start the MCP server now.</p>
    """)

if __name__ == "__main__":
    uvicorn.run(app, host=settings.SERVER_HOST, port=settings.SERVER_PORT)
