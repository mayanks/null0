# Kuvera-MCP — Technical Specification

## 1. Project Overview

Kuvera-MCP is a Python MCP server that gives AI assistants (Claude, ChatGPT, etc.) access to a user's Kuvera mutual fund portfolio. The user supplies their ephemeral Kuvera session token at query time; no credentials are stored server-side or in logs. The same process also serves a static marketing/landing page.

**Key constraints:**
- User passes their Kuvera JWT token per-request as a tool parameter — no server-side auth
- Tokens must never appear in logs (redacted before any log write)
- No Kuvera data is persisted server-side
- Deployed to exe.dev — platform handles SSL termination and proxying; the app binds on `0.0.0.0:$PORT`

---

## 2. Architecture

```
exe.dev edge  ←── SSL termination + reverse proxy
      │
      ▼
uvicorn  0.0.0.0:$PORT  (single worker — required by SSE transport)
Starlette app
  ├── GET /health       → health check (always first)
  ├── /mcp             → StreamableHTTP MCP transport
  ├── /sse             → SSE MCP transport
  └── /*               → StaticFiles (landing page)
         │
         ▼
   KuveraClient  →  https://api.kuvera.in
```

Both MCP transports share the same `Server` instance and expose the same tool set. Session state is per-connection, never persisted.

---

## 3. Technology Stack

| Layer | Choice | Reason |
|---|---|---|
| MCP server | `mcp` Python SDK (official) | First-party; supports SSE and Streamable HTTP transports |
| ASGI server | `uvicorn` | Standard pairing with Starlette |
| Web framework | `starlette` | Lightweight; MCP SDK transport adapters are Starlette-native; has built-in StaticFiles |
| HTTP client | `httpx` (async) | Native async; clean API for calling Kuvera |
| Rate limiting | `slowapi` | Starlette-compatible per-IP rate limiting |
| Structured logging | `python-json-logger` | JSON log output for operational observability |
| Static site | Plain HTML5 + Tailwind CSS (vendored) | Zero build step; Starlette serves files directly |
| Python version | 3.11+ | Async support, typing improvements |

---

## 4. Repository Structure

```
kuvera-mcp/
├── server.py                    # Starlette app entry point — mounts MCP transports + StaticFiles
├── kuvera_client.py             # Async Kuvera API client (all httpx calls centralised here)
├── tools/
│   ├── __init__.py
│   ├── account.py               # validateToken, getAccountInformation
│   ├── portfolio.py             # getPortfolios, switchPortfolio, getPortfolioPerformance
│   ├── holdings.py              # getHoldings
│   └── funds.py                 # getFundDetails, getEquityDistribution
├── static/                      # Served by Starlette StaticFiles at /
│   ├── index.html               # Landing / marketing page
│   ├── privacy.html             # Privacy policy (standalone page)
│   ├── robots.txt               # Disallow crawling of /mcp and /sse
│   └── assets/
│       ├── style.css            # Custom overrides beyond Tailwind utility classes
│       └── tailwind.min.css     # Vendored Tailwind CSS build (no CDN dependency)
├── tests/
│   ├── __init__.py
│   ├── test_kuvera_client.py    # Unit tests — mocked httpx responses via respx
│   └── test_tools.py            # Tool-level tests — mocked KuveraClient
├── requirements.txt             # Pinned production dependencies (exact versions)
├── requirements-dev.txt         # pytest, pytest-asyncio, respx, httpx
├── .env.example                 # Env var template — no secrets committed
├── .gitignore
├── spec.md                      # This file
├── CLAUDE.md                    # Agent build/test/deploy instructions
└── README.md                    # User-facing documentation
```

---

## 5. MCP Server — `server.py`

### 5.1 Responsibilities

- Apply `TokenRedactionFilter` to the root logger — **first thing, before any other setup**
- Configure structured JSON logging via `python-json-logger`
- Validate `KUVERA_API_BASE_URL` at startup against an allowlist — refuse to start if value is not `https://api.kuvera.in` (see Section 7.1)
- Create and manage the shared `httpx.AsyncClient` via Starlette's `lifespan` context manager
- Create a single `mcp.Server` instance named `"Kuvera"` version `"1.0.0"`
- Register all tools by calling each tool module's `register(server)` function
- Register routes in this exact order (Starlette evaluates in mount order):
  1. `GET /health` — health check endpoint, returns `{"status": "ok"}` with HTTP 200
  2. `/sse` — `SseServerTransport`
  3. `/mcp` — `StreamableHTTPSessionManager`
  4. `/*` — `StaticFiles` pointing to `static/` with `html=True`
- Add `CORSMiddleware` — origins from `CORS_ALLOW_ORIGINS` env var (default `*`), methods `GET POST OPTIONS`, headers `Content-Type Authorization Accept`
- Add `SecurityHeadersMiddleware` (custom, see Section 12) — sets `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Content-Security-Policy` on all responses
- Add `slowapi` rate limiter — default 60 requests/minute per IP on all MCP endpoints; 10 requests/minute on `validateToken`
- Read `PORT` from environment (default `8000`) and `HOST` (default `0.0.0.0`)
- Entry point: `uvicorn server:app --host $HOST --port $PORT --workers 1 --timeout-graceful-shutdown 30`

### 5.2 Transports

| Path | Transport class | Notes |
|---|---|---|
| `/sse` | `mcp.server.sse.SseServerTransport` | Required by Claude Desktop today |
| `/mcp` | `mcp.server.streamable_http.StreamableHTTPSessionManager` | Newer standard; stateless per request |

**Single-worker requirement:** The SSE transport maintains in-process connection state correlating the initial GET handshake with subsequent POST messages. Running multiple workers would cause POST requests to land on a different worker than the one holding the SSE connection, silently dropping messages. The app **must** run with `--workers 1`. This is not a limitation of the Streamable HTTP transport (`/mcp`), which is fully stateless per request.

**Graceful shutdown:** uvicorn is started with `--timeout-graceful-shutdown 30`. On `SIGTERM`, uvicorn stops accepting new connections and waits up to 30 seconds for existing SSE connections to drain before force-closing. AI clients should implement SSE reconnect logic for resilience.

**Future migration note:** Once Claude Desktop adds native Streamable HTTP support, the `/sse` transport can be removed. This eliminates the single-worker constraint entirely and enables horizontal scaling. Track the upstream MCP SDK and Claude Desktop changelogs for this transition.

### 5.3 Tool Registration Pattern

Each tool module exposes a `register(server: mcp.Server) -> None` function that calls `server.tool(...)` for each tool it owns. `server.py` imports and calls each module's `register` function. This keeps `server.py` thin and tool logic isolated.

---

## 6. Tool Definitions

Every tool receives a `token: str` parameter. Before making any API call, every tool must call `KuveraClient.validate_jwt_format(token)` and return an error message if it fails — this is a structural check only (three base64url segments separated by dots), not a signature verification. Tools must **never log the token value**. On client error, tools return an empty JSON object or array as a text string rather than raising.

---

### Tool: `validateToken`
**Module:** `tools/account.py`

**Description:**
> Validate if the token is valid. You need to validate the token before using any other tool. Ask the user to get the token after logging in to Kuvera on a browser and then get the token from the console using `localStorage.getItem('vue-authenticate.vueauth_token')`. If the user provides a wrong token, ask the user to provide the correct token.

**Input schema:** `token: str`

**Behaviour:** Call `KuveraClient.get_account_info(token)`. Return `"true"` if valid account data is returned, `"false"` otherwise.

---

### Tool: `getAccountInformation`
**Module:** `tools/account.py`

**Description:**
> Get user account information with portfolio details. Requires a valid token.
> These are high level information which provides user information, their current portfolio and their primary portfolio.

**Input schema:** `token: str`

**Return fields:**
- `id`, `name`, `email`, `onboarding_state`, `primary_portfolio_id`
- `current_portfolio`: `id`, `name`, `onboarding_state`, `mode_of_investment`, `aof_status`
- `primary_portfolio`: `id`, `name`, `onboarding_state`, `mode_of_investment`, `aof_status`, `email`

**Return:** JSON object as text. `"{}"` on error.

---

### Tool: `getPortfolios`
**Module:** `tools/portfolio.py`

**Description:**
> Get list of all portfolios with detailed information. Requires a valid token.
> Portfolio is a Kuvera terminology. It means an investment account. A user can have multiple portfolios. A portfolio can be single or joint. If `onboarding_form_status` is 13, the user can invest in mutual funds. Else the account is not active.

**Input schema:** `token: str`

**Return fields (array of):**
- `portfolio_id`, `account_status`, `portfolio_name`, `mode_of_investment`, `onboarding_form_state`, `portfolio_code`
- `applicants[]`: `id`, `name`, `gender`, `date_of_birth`, `marital_status`, `country_of_birth`
- `nominees[]`: `name`, `date_of_birth`, `relationship`

**Return:** JSON array as text.

---

### Tool: `getFundDetails`
**Module:** `tools/funds.py`

**Description:**
> Get details of a mutual fund. Provide a list of fund codes and a valid token. Returns AUM, category, code, expense ratio, name, NAV, NAV date, returns, and volatility for each fund.

**Input schema:** `fundCodes: list[str]`, `token: str`

**Validation:**
- `fundCodes` must contain between 1 and 20 items (inclusive). Return an error string if exceeded.
- Each fund code must match the pattern `^[A-Z0-9\-]{1,20}$`. Reject invalid codes with an error string.

**Return:** JSON object keyed by fund code. `"{}"` if no data found.

---

### Tool: `getEquityDistribution`
**Module:** `tools/funds.py`

**Description:**
> Get equity distribution in a fund for the current value of investment. Provide a fund code and a valid token.

**Input schema:** `fundCode: str`, `current_value: float`, `token: str`

**Validation:**
- `fundCode` must match `^[A-Z0-9\-]{1,20}$`.
- `current_value` must be a finite, positive number (`math.isfinite(current_value) and current_value > 0`). Return an error string otherwise.

**Return:** JSON object as text.

---

### Tool: `getHoldings`
**Module:** `tools/holdings.py`

**Description:**
> Get list of all mutual funds in which the user has invested. Each holding has name, amount, invested value, and current value (units × NAV). Requires a valid token.

**Input schema:** `token: str`

**Return:** JSON array as text.

---

### Tool: `getPortfolioPerformance`
**Module:** `tools/portfolio.py`

**Description:**
> Get performance data for all user portfolios. Requires a valid token.

**Input schema:** `token: str`

**Return fields (array of):**
- `portfolio_id`, `current_value`, `current_gain`, `current_gain_percent`
- `one_day_gain`, `one_day_gain_percent`
- `invested`, `current_xirr`, `alltime_xirr`
- `alltime_return`, `alltime_abs_percentage`, `alltime_abs_return`
- `portfolio_type` (`"self"` or `"managed"`)
- `mutual_funds` — mutual funds performance breakdown

**Return:** JSON array as text.

---

### Tool: `switchPortfolio`
**Module:** `tools/portfolio.py`

**Description:**
> Switch the current active portfolio to a different portfolio. After switching, the `current_portfolio` in account information updates and all subsequent operations reflect the new portfolio context.

**Input schema:** `portfolioId: str`, `token: str`

**Validation:**
- `portfolioId` must match `^\d{1,10}$` (numeric string). Reject with an error string otherwise.

**Return:** JSON object with `success` (bool), `data` (on success), or `error` (on failure).

---

### Extensibility

New tools should be added as functions in an appropriate `tools/*.py` module (or a new module), registered in that module's `register(server)` function, and called from `server.py`. This spec will be updated when new tools are defined.

---

## 7. Kuvera API Client — `kuvera_client.py`

### 7.1 Design

All HTTP calls to Kuvera are centralised here. No tool module may import `httpx` directly.

**Class:** `KuveraClient` — accepts a shared `httpx.AsyncClient` via constructor injection for testability.

**Base URL:** configurable via `KUVERA_API_BASE_URL` env var, defaulting to `https://api.kuvera.in`.

**Startup validation:** At app startup (before accepting any requests), validate that `KUVERA_API_BASE_URL` equals exactly `https://api.kuvera.in`. If not, log a fatal error and call `sys.exit(1)`. This prevents a misconfigured or tampered env var from redirecting all token-bearing requests to an attacker-controlled server.

**Request headers:** Every request to Kuvera must include:
```
Authorization: Bearer <token>
User-Agent: cp-app/1.0
Accept: application/json
Content-Type: application/json
```

**JWT format validation:** Implement `validate_jwt_format(token: str) -> bool` as a static method. A valid JWT is three base64url-encoded segments separated by dots, matching the pattern `^[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+$`. This is a structural check only — no signature verification. Reject tokens that do not match (contain whitespace, control characters, or wrong structure) before placing them in any HTTP header. This prevents header injection via `\r\n` characters.

### 7.2 Methods — Endpoint Details

#### `get_account_info(token: str)`
- **Method:** `GET`
- **URL:** `/api/v3/user/info.json`
- **Response shape:** JSON object; extract and return only:
  ```
  id, name, email, onboarding_state, primary_portfolio_id,
  current_portfolio: {id, name, onboarding_state, mode_of_investment, aof_status},
  primary_portfolio: {id, name, onboarding_state, mode_of_investment, aof_status, email}
  ```
- **On error / non-OK response:** return `None`

---

#### `get_portfolios(token: str)`
- **Method:** `GET`
- **URL:** `/api/users_service/v5/portfolio.json?v=1.238.2`
- **Response shape:** JSON array; for each element extract:
  ```
  portfolio_id (from x.id)
  account_status (from x.aof_status)
  portfolio_name, mode_of_investment, onboarding_form_state, portfolio_code
  applicants: built from x.primary_applicant, x.secondary_applicant1, x.secondary_applicant2
              (include only those that are non-null; each: id, name, gender, date_of_birth,
               marital_status, country_of_birth)
  nominees: from x.nominees array (each: name, date_of_birth, relationship)
  ```
- **On error:** return `[]`

---

#### `get_fund_details(fund_codes: list[str], token: str)`
- **Method:** `GET`
- **URL:** `/mf/api/v5/fund_schemes/{codes}.json` where `{codes}` is the fund codes joined with `|` and then URL-encoded (e.g. `CODE1%7CCODE2%7CCODE3`)
- **Response shape:** JSON array; build and return a dict keyed by `fund.code`:
  ```
  aum, category, code, expense_ratio, name, fund_name,
  nav (from bigFund.nav.nav),
  nav_date (from bigFund.nav.date),
  returns, volatility
  ```
- **On error:** return `{}`

---

#### `get_holdings(token: str)`
- **Method:** Two sequential API calls:
  1. `GET /api/v3/portfolio/holdings.json?v=1.238.2` — returns a dict keyed by fund code, each value is a list of holding objects
  2. `GET /mf/api/v5/fund_schemes/{all_fund_codes}.json` — call `get_fund_details` with all fund codes from step 1
- **Response shape:** flat list of holding objects, one per folio per fund:
  ```
  code (fund code),
  folio_number (from x.folioNumber, default "Unknown"),
  units (from x.units, default 0.0),
  invested_value (from x.allottedAmount, default 0.0),
  current_value (units * nav, where nav comes from fund details),
  fund_details (the full fund detail object from step 2)
  ```
- **On error at step 1:** return `[]`

---

#### `get_equity_distribution(fund_code: str, current_value: float, token: str)`
- **Method:** `GET`
- **URL:** `/mf/api/v5/fund_investment_stats/{fund_code}.json` (fund code URL-encoded)
- **Response processing:** from `data[fund_code].top_holdings`, filter entries where `security_asset_class == "Equity"`, then map each to:
  ```
  portfolio_date, company_name, percentage_to_aum, ticker,
  proportionate_amount (= percentage_to_aum * current_value / 100)
  ```
- **On error:** return `[]`

---

#### `get_portfolio_performance(token: str)`
- **Method:** `GET`
- **URL:** `/api/v3/user/portfolio_performance.json?v=1.239.2`
- **Response shape:** JSON object `{status: "success", data: {<portfolio_id>: {...}}}`. Return `[]` if `response.status != "success"` or `response.data` is absent. Otherwise convert `data` (an object keyed by portfolio ID strings) to an array:
  ```
  portfolio_id (int),
  current_value, current_gain, current_gain_percent,
  one_day_gain, one_day_gain_percent,
  invested, current_xirr, alltime_xirr,
  alltime_return, alltime_abs_percentage, alltime_abs_return,
  portfolio_type, mutual_funds
  ```

---

#### `switch_portfolio(portfolio_id: str, token: str)`
- **Method:** `POST`
- **URL:** `/api/v3/portfolio/switch/{portfolio_id}.json?v=1.239.1`
- **Body:** empty (no request body)
- **On success (2xx):** return `{"success": True, "data": <response json>}`
- **On HTTP error:** return `{"success": False, "error": "HTTP <status>"}`
- **On network error:** return `{"success": False, "error": "Request failed"}`

---

### 7.3 Unexposed API Functions

`api.ts` contains `getPortfolioReturns` (`GET /api/v4/user/returns.json?v=1.239.2`) which is not exposed as an MCP tool. This returns per-portfolio return summaries (current value, gains, invested). It can be added as a future tool.

### 7.4 HTTP Client Lifecycle

The shared `httpx.AsyncClient` is created during app startup using Starlette's `lifespan` context manager and closed on shutdown. It is never created per-request (which would waste a TCP+TLS handshake per call).

```
lifespan startup:
  client = httpx.AsyncClient(
      base_url=KUVERA_API_BASE_URL,
      timeout=httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0),
      limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
  )

lifespan shutdown:
  await client.aclose()
```

The `KuveraClient` is instantiated with this shared client and passed into tool modules.

### 7.5 Error Handling

- Return `None`, `{}`, or `[]` (as appropriate per method) on HTTP errors — never raise to callers
- Log at `WARNING` level on error — include HTTP status code and path only, never the token, request headers, or response body
- On timeout, return the appropriate empty value — do not log the token from the exception

### 7.6 Logging Policy

- Implement `TokenRedactionFilter(logging.Filter)` — overrides both `filter(record)` and `formatException` to scrub JWT-pattern strings (`[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+`) from `record.getMessage()` and `record.exc_text` before any handler writes the record
- Apply to the root logger at startup before any other code runs
- httpx exceptions embed the full request (including `Authorization` headers) in their string representation — catch all `httpx.HTTPError` subclasses and log only a generic message, never `str(exc)` directly
- Never log response bodies that may contain PII

---

## 8. Static Website

### 8.1 Serving

Starlette `StaticFiles` mounts the `static/` directory at `/` with `html=True`:
- `/` → `static/index.html`
- `/privacy` → `static/privacy.html`
- `/assets/style.css` → `static/assets/style.css`
- `/assets/tailwind.min.css` → `static/assets/tailwind.min.css`
- `/robots.txt` → `static/robots.txt`

MCP paths (`/mcp`, `/sse`) and `/health` are registered before `StaticFiles` — they take priority.

Static files are served with `Cache-Control: public, max-age=86400` headers. Implement via a custom `StaticFiles` subclass or a middleware that appends cache headers only for responses originating from the static mount.

### 8.2 Technology

- Plain HTML5 — no JavaScript framework, no build step
- Tailwind CSS **vendored** into `static/assets/tailwind.min.css` — no CDN script tag; eliminates the CDN supply-chain risk and the need for an SRI hash
- Custom CSS in `static/assets/style.css` for anything beyond Tailwind utilities
- Dark theme: background `#0f0f0f` / `#111827`, accent `#6366f1` (indigo-500)
- Responsive (mobile-first)
- No cookies, no analytics, no trackers

### 8.3 `robots.txt`

```
User-agent: *
Disallow: /mcp
Disallow: /sse
Disallow: /health
```

### 8.4 `index.html` — Landing Page Sections

1. **Nav bar** — sticky, dark bg. Logo "Kuvera MCP" on left. Links: "Privacy" (`/privacy`), "GitHub" (repo URL).

2. **Hero** — full-width, centered.
   - Headline: *"Talk to your Kuvera portfolio with AI"*
   - Sub-headline: *"An open-source MCP server that connects Claude, ChatGPT, and other AI assistants to your Kuvera mutual fund portfolio — in real time."*
   - Badge row: "For personal use · No data stored · Open source"
   - CTA button: "Get started →" (smooth-scrolls to setup section)

3. **What can you ask?** — card grid, one card per tool.
   - Each card: icon + short title + one-line description
   - Examples: "Check holdings", "Portfolio performance", "Fund details", "Switch portfolio", "Validate session", "Equity breakdown"

4. **How it works** — 3-step horizontal flow:
   1. Get your Kuvera session token from the browser console
   2. Configure the MCP server URL in your AI client
   3. Ask your AI anything about your portfolio

5. **Setup guide** — tabbed section, one tab per client:
   - **Claude Desktop** — JSON snippet for `claude_desktop_config.json` with `mcpServers` config pointing to `https://<domain>/sse`
   - **Claude.ai** — connector URL: `https://<domain>/sse`
   - **Generic MCP client** — note that both `/sse` (SSE) and `/mcp` (Streamable HTTP) are available

6. **Getting your Kuvera token** — numbered steps with monospace code block:
   1. Log in to kuvera.in in your browser
   2. Open DevTools → Console (F12)
   3. Paste and run: `localStorage.getItem('vue-authenticate.vueauth_token')`
   4. Copy the returned string — this is your JWT token
   5. Paste it when your AI assistant asks for it
   - Note: token expires with your browser session; re-fetch if it stops working
   - Security note: this token grants access to your Kuvera account (read and transact). If you suspect it has been exposed, log out of kuvera.in immediately to invalidate it.

7. **Privacy at a glance** — 3–4 bullet summary with link to full `/privacy` page.

8. **Footer** — "Built for fun · Not affiliated with Kuvera · Open source on GitHub"

### 8.5 `privacy.html` — Privacy Policy Page

Full standalone page with the following sections:

**Token handling**
- Your Kuvera token is a JWT used ephemerally, solely to authenticate the single API request you triggered.
- The token is never written to any database, file, cache, or log.
- Token values match a JWT pattern and are explicitly redacted from application-level logs — including exception stack traces — before any write occurs.
- The token exists in server memory only for the milliseconds required to complete the API call, then is discarded.

**Data handling**
- No Kuvera portfolio data, account data, or personal financial information is stored on our servers.
- API responses are forwarded directly to your AI client and not written to any persistent storage.
- We have no access to your data after the API call completes.

**Server logs**
- Standard platform access logs (request path, timestamp, HTTP status code) may be retained by exe.dev for operational purposes. They do not contain tokens or financial data.
- Application-level logs contain no tokens or user data. Logs are structured JSON and include only request metadata (path, status, duration).

**Token scope and revocation**
- Your Kuvera token can be used to read portfolio data and execute transactions on your behalf. Treat it like a password.
- If you believe your token has been compromised, log out of kuvera.in immediately. This invalidates the session token.

**Project nature**
- This is a personal, for-fun, open-source project. No commercial terms, no monetization, no advertising, no data selling.
- Not affiliated with, endorsed by, or partnered with Kuvera / Arevuk Advisory Services Pvt. Ltd.

**Third parties**
- No third-party analytics, trackers, or SDKs are included on this website or in the MCP server.
- No cookies are set. Tailwind CSS is self-hosted — no external CDN requests from this site.

**Contact**
- Questions or concerns: open an issue on the GitHub repository.

---

## 9. Environment Variables

File: `.env.example` (never commit `.env`)

| Variable | Default | Purpose |
|---|---|---|
| `KUVERA_API_BASE_URL` | `https://api.kuvera.in` | Base URL for Kuvera API — validated at startup against this exact value |
| `KUVERA_API_TIMEOUT` | `15.0` | Read timeout in seconds for Kuvera API calls |
| `LOG_LEVEL` | `INFO` | Python logging level |
| `HOST` | `0.0.0.0` | uvicorn bind address |
| `PORT` | `8000` | uvicorn bind port (exe.dev injects this) |
| `CORS_ALLOW_ORIGINS` | `*` | Comma-separated list of allowed CORS origins |

---

## 10. Dependencies

### `requirements.txt` (pin exact versions with `==`)

- `mcp` — official MCP Python SDK
- `starlette` — ASGI framework
- `uvicorn[standard]` — ASGI server
- `httpx` — async HTTP client
- `slowapi` — per-IP rate limiting for Starlette
- `python-json-logger` — structured JSON log output
- `python-dotenv` — load `.env` file

### `requirements-dev.txt`

- `pytest`
- `pytest-asyncio`
- `respx` — httpx request mocker for tests
- All of `requirements.txt`

---

## 11. Testing

### Unit tests — `tests/test_kuvera_client.py`

- Use `respx` to mock all `httpx` calls
- For each `KuveraClient` method test:
  - Happy path: 200 response → correct parsed return value
  - Error path: 401 or 500 → `None` or error dict returned, no exception raised
  - Timeout path: `httpx.TimeoutException` → `{"error": "Kuvera API request timed out"}` returned
  - Token redaction: capture log output and assert JWT string does not appear in any log record, including simulated exception paths
- Test `validate_jwt_format`:
  - Valid JWT (three base64url segments) → `True`
  - Token with `\r\n` injection → `False`
  - Empty string → `False`
  - Two-segment string → `False`

### Tool tests — `tests/test_tools.py`

- Mock `KuveraClient` at the module level
- For each tool:
  - Assert return value is `{"content": [{"type": "text", "text": <string>}]}`
  - Assert the text is valid JSON (parseable)
  - Assert error case (client returns `None`) returns `"{}"` or `"[]"` rather than raising
- Test input validation:
  - `getFundDetails` with 21 fund codes → error string returned, no API call made
  - `getFundDetails` with malformed fund code → error string returned
  - `getEquityDistribution` with negative `current_value` → error string returned
  - `switchPortfolio` with non-numeric `portfolioId` → error string returned
  - Any tool with a token that fails `validate_jwt_format` → error string returned

### Running tests

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

---

## 12. Security & Privacy Implementation Requirements

1. **Token redaction (JWT-anchored)** — `TokenRedactionFilter` must scrub strings matching the JWT pattern `[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+` from both `record.getMessage()` and `record.exc_text`. Apply to the root logger as the absolute first operation in `server.py`. Never pass `str(httpx_exception)` to any `logger.*` call — always use a hand-written generic message.

2. **JWT format validation** — `KuveraClient.validate_jwt_format(token)` must be called before placing any token in an HTTP header. This guards against header injection via CRLF characters and gives a clean error to the AI client for obviously invalid tokens.

3. **`KUVERA_API_BASE_URL` allowlist** — validate at startup against `https://api.kuvera.in` exactly. Log `CRITICAL` and exit if the value differs. This prevents a compromised env var from exfiltrating user tokens.

4. **Rate limiting** — `slowapi` limiter applied at the Starlette app level: 60 req/min per IP on `/mcp` and `/sse`; 10 req/min per IP specifically on the `validateToken` tool path. Exceeded limits return HTTP 429.

5. **HTTP security headers** — implement `SecurityHeadersMiddleware` that adds the following to every response:
   ```
   X-Content-Type-Options: nosniff
   X-Frame-Options: DENY
   Referrer-Policy: no-referrer
   Content-Security-Policy: default-src 'self'; style-src 'self'; script-src 'none'; object-src 'none'
   ```

6. **Input validation** — all tool-level parameter constraints defined in Section 6 must be enforced in the tool handler before calling `KuveraClient`. Invalid inputs return an error string to the AI client, never an exception.

7. **Request body size limit** — configure Starlette/uvicorn to reject request bodies larger than 64 KB for MCP endpoints. This prevents memory exhaustion from oversized payloads.

8. **No persistent storage** — no SQLite, Redis, files, or any storage layer. Stateless per-request.

9. **No secrets in repo** — `.env` is gitignored; `.env.example` contains only placeholder values.

10. **Dependency pinning** — `requirements.txt` pins exact versions (`==`) for all dependencies.
