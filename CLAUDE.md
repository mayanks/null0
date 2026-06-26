# Kuvera-MCP — Agent Instructions

## Project Summary

Python MCP server + static landing page. Read `spec.md` for full technical details before writing any code.

## Build Order

Follow this order — later steps depend on earlier ones:

1. `requirements.txt` and `requirements-dev.txt`
2. `.env.example` and `.gitignore`
3. `kuvera_client.py`
4. `tools/__init__.py`, then each tool module (`account.py`, `portfolio.py`, `holdings.py`, `funds.py`)
5. `server.py`
6. `tests/test_kuvera_client.py`, `tests/test_tools.py`
7. `static/index.html`, `static/privacy.html`, `static/assets/style.css`

## Key Implementation Notes

### Kuvera API auth

All requests to `api.kuvera.in` use a Bearer token in the Authorization header:

```
Authorization: Bearer <token>
```

The token is obtained by the user from their browser after logging in to kuvera.in:

```js
localStorage.getItem('vue-authenticate.vueauth_token')
```

The user pastes this token into the AI assistant when prompted. It is passed to every tool call as the `token` parameter and forwarded directly to Kuvera API calls. It is never stored.

### MCP SDK transport mounting

Check the installed `mcp` SDK version's actual import paths before writing `server.py` — the SDK is evolving. Patterns to look for:

- SSE: `mcp.server.sse.SseServerTransport`
- Streamable HTTP: `mcp.server.streamable_http.StreamableHTTPSessionManager`

If a transport isn't available in the installed version, implement the other and leave a `# TODO` comment.

### Route order in server.py

Register `/sse` and `/mcp` routes **before** mounting `StaticFiles`. Starlette evaluates mounts in order — if `StaticFiles` is mounted first it will intercept all paths.

### Token redaction

Apply `TokenRedactionFilter` to the root logger in `server.py` before any other setup. This is the safety net — do not rely on individual log calls being careful.

### Tool return format

Every tool must return:
```python
{"content": [{"type": "text", "text": some_json_string}]}
```
Never return raw dicts or raise exceptions from tool handlers. On error return `"{}"` or `"[]"` as appropriate.

## Running Locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
uvicorn server:app --host 0.0.0.0 --port 8000 --reload
```

- Landing page: `http://localhost:8000/`
- Privacy page: `http://localhost:8000/privacy`
- MCP SSE endpoint: `http://localhost:8000/sse`
- MCP HTTP endpoint: `http://localhost:8000/mcp`

## Running Tests

```bash
pytest tests/ -v
```

All tests must pass before the implementation is considered complete. Tests use `respx` to mock httpx — do not make real network calls in tests.

## Deployment (exe.dev)

exe.dev manages the process, SSL, and proxying. The app binds on `0.0.0.0:$PORT`.

```bash
# First deploy on exe.dev VM:
git clone <repo-url> kuvera-mcp
cd kuvera-mcp
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

# Start command to configure in exe.dev dashboard:
uvicorn server:app --host 0.0.0.0 --port $PORT
```

Update deploy:
```bash
git pull
source .venv/bin/activate
pip install -r requirements.txt
# Restart the process via exe.dev dashboard
```

## Definition of Done

- [ ] `pytest tests/ -v` passes with no failures
- [ ] `uvicorn server:app` starts without errors
- [ ] `GET /` returns the landing page HTML
- [ ] `GET /privacy` returns the privacy page HTML
- [ ] `/sse` endpoint responds to MCP SSE handshake
- [ ] `/mcp` endpoint responds to MCP HTTP requests
- [ ] Token value does not appear in any log output
- [ ] `.env` is not committed (verify with `git status`)
