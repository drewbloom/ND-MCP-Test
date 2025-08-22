# NetDocuments MCP (Draft)

Minimal remote MCP server for ChatGPT connectors that lets users **search** and **fetch** NetDocuments files via per-user OAuth (Authorization Code + PKCE). **Binary files are downloaded and converted to plaintext** (PDF/DOCX/TXT best effort) and returned to the model.

## What this is
- An **MCP** server exposing only two tools:
  - `search(query: string)` → `{ results: [{ id, title, text, url }] }`
  - `fetch(id: string)` → `{ id, title, text, url, metadata }`
- Built for **ChatGPT Connectors** (Deep Research & chat).
- Uses **Authorization Code + PKCE** with **scope=read**.

> Connectors do **not** upload the original binary like drag-and-drop; they consume returned **text** and **urls**.

---

## Quickstart (Replit or local)

1. **Install deps**
```bash
pip install -r requirements.txt
```

2. **Create `.env`** from `.env.example` and fill in:
   - `ND_CLIENT_ID=...`
   - `ND_CLIENT_SECRET=...`
   - `ND_REDIRECT_URI=https://<your-replit-host>.repl.co/oauth/callback`
   - (Optional) adjust `SEARCH_DEFAULT_TOP`, `MAX_FETCH_CHARS`, region URLs.

3. **Authorize once** (saves tokens to `tokens.json`):
```bash
python oauth_runner.py
# browser opens: complete the ND login/approval
```

4. **Run the MCP server (SSE)**:
```bash
python app.py
```
Confirm your repl URL ends with **`/sse/`** (FastMCP exposes this automatically).

5. **Connect in ChatGPT → Settings → Connectors**  
   Add your `/sse/` URL, allow `search` and `fetch` (approval: never). Test a query.

---

## Tool behavior

### `search(query: string)`
- Accepts a **single string** (per MCP spec), but also supports an inline mini-language to pass ND params:
  - `cabinetId:<id>` — Cabinet to search (if omitted, uses the first available cabinet for the user).
  - `top:<n>` — Page size (default **50**; ND allows up to 500).
  - `orderby:<relevance|lastMod>` — Sort order (desc).
  - `select:<standardAttributes>` — Returned fields set.
- Remaining words are treated as the **full-text `q`** parameter (pass ND query syntax directly).
- Returns up to `top` results, each with `{id, title, text (snippet), url}`.

### `fetch(id: string)`
- Looks up metadata, downloads **binary** via `GET /v1/Document/{id}?base64=true`, decodes, and extracts plaintext:
  - PDF → `pdfminer.six`
  - DOCX → `python-docx` (toggle via `ENABLE_DOCX=true` in `.env`)
  - TXT/CSV/JSON → decoded as text
  - Others → best-effort decode; if not extractable, `text` is empty with metadata hint.
- Truncates output over `MAX_FETCH_CHARS` with `metadata.truncated=true`.

---

## Notes & limits

- **Per-user OAuth**: this MVP stores a **single** user's tokens in `tokens.json`. For multi-user, add a session/token store keyed per SSE connection or user subject.
- **Cross-cabinet search**: supported by ND. If you omit `cabinetId`, we attempt a cross-cabinet call. To be precise per ND docs, some scenarios require special qualifiers in `q`. Supply full ND syntax in your query if needed.
- **Rate limits**: the client retries on 401 by refreshing; consider backoff for 429 (future work).
- **Security**: scope is `read`. Do not log tokens. Consider encrypting `tokens.json` for real deployments.

---

## Environment variables

See `.env.example`. All values are read from `.env`.

- `ND_CLIENT_ID`, `ND_CLIENT_SECRET`, `ND_REDIRECT_URI`, `ND_OAUTH_SCOPE`
- `ND_AUTH_AUTHORIZE_URL`, `ND_AUTH_TOKEN_URL`, `ND_API_BASE` (US by default)
- `SERVER_HOST`, `SERVER_PORT`
- `SEARCH_DEFAULT_TOP`, `SEARCH_DEFAULT_ORDER`, `MAX_FETCH_CHARS`, `ENABLE_DOCX`

---

## Development

- Extend `nd_client.search(...)` to expose more ND search params as needed.
- Consider adding `$skiptoken` support for paging if you want "Load more".
- Add per-connection token scoping if you expect multiple concurrent users.

---

## License
MIT (draft)
