# Kuvera MCP

An open-source MCP server that connects AI assistants (Claude, ChatGPT, and others) to your [Kuvera](https://kuvera.in) mutual fund portfolio — in real time.

> **Personal project. Not affiliated with Kuvera / Arevuk Advisory Services.**

---

## What can you ask?

Once connected, you can ask your AI assistant things like:

- "What are my current holdings and their present value?"
- "How has my portfolio performed this year?"
- "What is the expense ratio and 3-year return of fund XYZ?"
- "Switch to my joint portfolio and show me its performance."
- "What is the equity distribution in my large-cap fund?"

---

## How it works

1. Log in to [kuvera.in](https://kuvera.in) in your browser
2. Open the browser console (F12 → Console) and run:
   ```js
   localStorage.getItem('vue-authenticate.vueauth_token')
   ```
3. Copy the returned token string
4. Configure your AI client to use this MCP server (see setup below)
5. When your assistant asks for your Kuvera token, paste it in

The token is used only for the duration of each API call and is never stored anywhere. See the [Privacy Policy](#privacy) section for details.

---

## Setup

### Claude Desktop — Production

Add the following to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "kuvera": {
      "url": "https://null0.exe.xyz/sse"
    }
  }
}
```

### Claude Desktop — Local Development

If you are running the server locally, use `localhost` instead:

```json
{
  "mcpServers": {
    "kuvera": {
      "url": "http://localhost:8000/sse"
    }
  }
}
```

The `claude_desktop_config.json` file is located at:
- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

After editing the file, restart Claude Desktop for the changes to take effect.

### Claude.ai (web)

Add a new MCP connector with URL:
```
https://null0.exe.xyz/sse
```

### Generic MCP client

Two transports are available:

| Transport | URL |
|---|---|
| SSE (broader compatibility) | `https://null0.exe.xyz/sse` |
| Streamable HTTP (newer standard) | `https://null0.exe.xyz/mcp` |

---

## Available Tools

| Tool | Description |
|---|---|
| `validateToken` | Verify your Kuvera session token is valid |
| `getAccountInformation` | Account details, current and primary portfolio |
| `getPortfolios` | All portfolios with applicant and nominee details |
| `getHoldings` | All mutual fund holdings with invested and current value |
| `getPortfolioPerformance` | XIRR, gains, and performance across all portfolios |
| `getFundDetails` | AUM, NAV, expense ratio, returns, and volatility for given fund codes |
| `getEquityDistribution` | Equity breakdown within a fund for a given investment value |
| `switchPortfolio` | Change the active portfolio context |

---

## Privacy

- **Your token is never stored.** It lives in server memory only for the milliseconds needed to complete the API call, then is discarded.
- **Token values are redacted from all logs** before any write occurs.
- **No portfolio or financial data is stored** on the server. Responses are forwarded directly to your AI client.
- No analytics, no trackers, no cookies.
- This is a personal, for-fun project with no commercial terms.

Full privacy policy: `https://null0.exe.xyz/privacy`

---

## Self-hosting / Development

### Requirements

- Python 3.11+
- An [exe.dev](https://exe.dev) VM or any server that can run a Python ASGI process

### Local setup

```bash
git clone https://github.com/mayanks/null0 kuvera-mcp
cd kuvera-mcp
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
uvicorn server:app --host 0.0.0.0 --port 8000 --reload
```

The server will be available at:
- Landing page: `http://localhost:8000/`
- MCP SSE endpoint: `http://localhost:8000/sse`
- MCP HTTP endpoint: `http://localhost:8000/mcp`

### Running tests

```bash
pytest tests/ -v
```

### Deployment (exe.dev)

```bash
# On the exe.dev VM:
git clone https://github.com/mayanks/null0 kuvera-mcp
cd kuvera-mcp
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

# Configure the following as the start command in the exe.dev dashboard:
uvicorn server:app --host 0.0.0.0 --port $PORT
```

To update after pushing changes:

```bash
git pull
source .venv/bin/activate
pip install -r requirements.txt
# Restart the process via the exe.dev dashboard
```

---

## Disclaimer

This project is not affiliated with, endorsed by, or partnered with Kuvera or Arevuk Advisory Services Pvt. Ltd. It is an independent, open-source tool built for personal use.
