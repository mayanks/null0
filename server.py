"""
Kuvera-MCP — Starlette ASGI application entry point.

Start command (REQUIRED: --workers 1 for SSE transport):
    uvicorn server:app --host $HOST --port $PORT --workers 1 --timeout-graceful-shutdown 30

Single-worker requirement:
    The SSE transport maintains in-process connection state correlating the initial
    GET handshake with subsequent POST messages. Multiple workers would cause POST
    requests to land on a different worker than the one holding the SSE connection,
    silently dropping messages.
"""

# ---------------------------------------------------------------------------
# Step 1: Apply TokenRedactionFilter to root logger — BEFORE anything else
# ---------------------------------------------------------------------------
import logging

from kuvera_client import TokenRedactionFilter

_redaction_filter = TokenRedactionFilter()
logging.getLogger().addFilter(_redaction_filter)

# ---------------------------------------------------------------------------
# Standard imports (after redaction filter is in place)
# ---------------------------------------------------------------------------
import contextlib
import json
import os
import sys
import time
from typing import Any, AsyncIterator

import httpx
import mcp.server.lowlevel as _lowlevel
import mcp.types as types
from dotenv import load_dotenv
from mcp.server.lowlevel import Server
from mcp.server.sse import SseServerTransport
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from pythonjsonlogger import jsonlogger
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send

# Tool modules
from tools.account import (
    TOOL_GET_ACCOUNT_INFORMATION,
    TOOL_VALIDATE_TOKEN,
    handle_get_account_information,
    handle_validate_token,
)
from tools.funds import (
    TOOL_GET_EQUITY_DISTRIBUTION,
    TOOL_GET_FUND_DETAILS,
    handle_get_equity_distribution,
    handle_get_fund_details,
)
from tools.holdings import TOOL_GET_HOLDINGS, handle_get_holdings
from tools.portfolio import (
    TOOL_GET_PORTFOLIO_PERFORMANCE,
    TOOL_GET_PORTFOLIOS,
    TOOL_SWITCH_PORTFOLIO,
    handle_get_portfolio_performance,
    handle_get_portfolios,
    handle_switch_portfolio,
)
from kuvera_client import KuveraClient

load_dotenv()

# ---------------------------------------------------------------------------
# Structured JSON logging configuration
# ---------------------------------------------------------------------------

_log_level = os.environ.get("LOG_LEVEL", "INFO").upper()

_handler = logging.StreamHandler()
_formatter = jsonlogger.JsonFormatter(
    fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
    rename_fields={"asctime": "timestamp", "levelname": "level", "name": "logger"},
)
_handler.setFormatter(_formatter)
_handler.addFilter(_redaction_filter)

_root_logger = logging.getLogger()
_root_logger.setLevel(_log_level)
# Remove default handlers, add our JSON handler
_root_logger.handlers.clear()
_root_logger.addHandler(_handler)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Startup validation — KUVERA_API_BASE_URL must be exactly this value
# ---------------------------------------------------------------------------

KUVERA_API_BASE_URL = os.environ.get("KUVERA_API_BASE_URL", "https://api.kuvera.in")

if KUVERA_API_BASE_URL != "https://api.kuvera.in":
    logging.getLogger(__name__).critical(
        "KUVERA_API_BASE_URL is not 'https://api.kuvera.in'. "
        "Refusing to start to prevent token exfiltration. "
        "Current value: %s",
        KUVERA_API_BASE_URL,
    )
    sys.exit(1)

KUVERA_API_TIMEOUT = float(os.environ.get("KUVERA_API_TIMEOUT", "15.0"))
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8000"))
CORS_ALLOW_ORIGINS = os.environ.get("CORS_ALLOW_ORIGINS", "*")

# ---------------------------------------------------------------------------
# MCP Server — single shared instance
# ---------------------------------------------------------------------------

mcp_server = Server("Kuvera", version="1.0.0")

# All tools across all modules
_ALL_TOOLS = [
    TOOL_VALIDATE_TOKEN,
    TOOL_GET_ACCOUNT_INFORMATION,
    TOOL_GET_PORTFOLIOS,
    TOOL_GET_PORTFOLIO_PERFORMANCE,
    TOOL_SWITCH_PORTFOLIO,
    TOOL_GET_HOLDINGS,
    TOOL_GET_FUND_DETAILS,
    TOOL_GET_EQUITY_DISTRIBUTION,
]

# Tool dispatch table — populated after client is available in lifespan
_TOOL_DISPATCH: dict[str, Any] = {}


@mcp_server.list_tools()
async def list_tools() -> list[types.Tool]:
    return _ALL_TOOLS


@mcp_server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    handler = _TOOL_DISPATCH.get(name)
    if handler is None:
        return [types.TextContent(type="text", text=f"Error: Unknown tool '{name}'")]
    result = await handler(arguments)
    # result is {"content": [{"type": "text", "text": ...}]}
    content = result.get("content", [])
    return [
        types.TextContent(type=item["type"], text=item["text"])
        for item in content
        if item.get("type") == "text"
    ]


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])


def _rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> Response:
    return JSONResponse(
        {"error": "Rate limit exceeded", "detail": str(exc.detail)},
        status_code=429,
    )


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


_SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"content-security-policy",
     b"default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; object-src 'none'"),
]


class SecurityHeadersMiddleware:
    """Pure ASGI middleware — injects security headers into http.response.start.
    Does NOT use BaseHTTPMiddleware to avoid buffering SSE streams."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Any) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(_SECURITY_HEADERS)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)


class RequestLoggingMiddleware:
    """Pure ASGI middleware — structured access logging without buffering."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.monotonic()
        status_holder: list[int] = []

        async def send_capturing_status(message: Any) -> None:
            if message["type"] == "http.response.start":
                status_holder.append(message.get("status", 0))
            await send(message)

        try:
            await self.app(scope, receive, send_capturing_status)
        finally:
            duration_ms = round((time.monotonic() - start) * 1000, 2)
            logger.info(
                "request",
                extra={
                    "path": scope.get("path", ""),
                    "method": scope.get("method", ""),
                    "status": status_holder[0] if status_holder else 0,
                    "duration_ms": duration_ms,
                },
            )


# ---------------------------------------------------------------------------
# Static files with Cache-Control header
# ---------------------------------------------------------------------------


class CachedStaticFiles(StaticFiles):
    """StaticFiles subclass that adds Cache-Control: public, max-age=86400."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def send_with_cache(message: Any) -> None:
            if message["type"] == "http.response.start":
                headers = dict(message.get("headers", []))
                headers[b"cache-control"] = b"public, max-age=86400"
                message = {**message, "headers": list(headers.items())}
            await send(message)

        await super().__call__(scope, receive, send_with_cache)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


async def privacy_page(request: Request) -> Response:
    """Serve privacy.html at /privacy (Starlette html=True only handles index.html)."""
    from starlette.responses import FileResponse
    return FileResponse("static/privacy.html")


async def about_page(request: Request) -> Response:
    """Serve about.html at /about."""
    from starlette.responses import FileResponse
    return FileResponse("static/about.html")


# ---------------------------------------------------------------------------
# Lifespan — httpx.AsyncClient + session manager lifecycle
# ---------------------------------------------------------------------------


@contextlib.asynccontextmanager
async def lifespan(app: Starlette) -> AsyncIterator[None]:
    """Create shared httpx.AsyncClient and wire up tool dispatch table."""
    client = httpx.AsyncClient(
        base_url=KUVERA_API_BASE_URL,
        timeout=httpx.Timeout(connect=5.0, read=KUVERA_API_TIMEOUT, write=5.0, pool=5.0),
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    )
    kuvera = KuveraClient(client)

    # Wire dispatch table — closures capture kuvera
    _TOOL_DISPATCH.update(
        {
            "validateToken": lambda args: handle_validate_token(args, kuvera),
            "getAccountInformation": lambda args: handle_get_account_information(args, kuvera),
            "getPortfolios": lambda args: handle_get_portfolios(args, kuvera),
            "getPortfolioPerformance": lambda args: handle_get_portfolio_performance(args, kuvera),
            "switchPortfolio": lambda args: handle_switch_portfolio(args, kuvera),
            "getHoldings": lambda args: handle_get_holdings(args, kuvera),
            "getFundDetails": lambda args: handle_get_fund_details(args, kuvera),
            "getEquityDistribution": lambda args: handle_get_equity_distribution(args, kuvera),
        }
    )

    # StreamableHTTP session manager lifecycle
    async with session_manager.run():
        logger.info("Kuvera-MCP server started")
        try:
            yield
        finally:
            await client.aclose()
            logger.info("Kuvera-MCP server shutdown")


# ---------------------------------------------------------------------------
# SSE transport
# ---------------------------------------------------------------------------

# SseServerTransport takes the POST endpoint path as argument
sse_transport = SseServerTransport("/sse/messages/")


async def handle_sse(request: Request) -> Response:
    """Handle SSE GET connection — establishes the MCP SSE session."""
    async with sse_transport.connect_sse(
        request.scope, request.receive, request._send  # type: ignore[attr-defined]
    ) as streams:
        await mcp_server.run(
            streams[0],
            streams[1],
            mcp_server.create_initialization_options(),
        )
    return Response()


# ---------------------------------------------------------------------------
# StreamableHTTP transport
# ---------------------------------------------------------------------------

session_manager = StreamableHTTPSessionManager(
    app=mcp_server,
    json_response=False,
    stateless=True,
)


# ---------------------------------------------------------------------------
# Starlette app assembly
# ---------------------------------------------------------------------------

# Route order: health → sse → mcp → static
routes = [
    Route("/health", endpoint=health, methods=["GET"]),
    # /privacy and /about served explicitly — StaticFiles html=True only serves index.html for /
    Route("/privacy", endpoint=privacy_page, methods=["GET"]),
    Route("/about", endpoint=about_page, methods=["GET"]),
    # SSE transport: GET /sse establishes stream, POST /sse/messages/ sends messages
    Route("/sse", endpoint=handle_sse, methods=["GET"]),
    Mount("/sse/messages", app=sse_transport.handle_post_message),
    # StreamableHTTP transport — handle_request is an ASGI app
    Mount("/mcp", app=session_manager.handle_request),
    # Static files (must come last — catches all remaining paths)
    Mount("/", app=CachedStaticFiles(directory="static", html=True)),
]

# Parse CORS origins
_cors_origins: list[str] = (
    [o.strip() for o in CORS_ALLOW_ORIGINS.split(",")]
    if CORS_ALLOW_ORIGINS != "*"
    else ["*"]
)

app = Starlette(
    routes=routes,
    lifespan=lifespan,
    middleware=[
        Middleware(
            CORSMiddleware,
            allow_origins=_cors_origins,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Content-Type", "Authorization", "Accept"],
        ),
        Middleware(SecurityHeadersMiddleware),
        Middleware(RequestLoggingMiddleware),
    ],
)

# Register rate limit exceeded handler
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
