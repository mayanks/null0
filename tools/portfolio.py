"""
Portfolio tools: getPortfolios, getPortfolioPerformance, switchPortfolio.
"""

import json
import re
from typing import Any

from loguru import logger

import mcp.types as types

from kuvera_client import KuveraClient

_PORTFOLIO_ID_RE = re.compile(r"^\d{1,10}$")

TOOL_GET_PORTFOLIOS = types.Tool(
    name="getPortfolios",
    description=(
        "Get list of all portfolios with detailed information. Requires a valid token.\n"
        "Portfolio is a Kuvera terminology. It means an investment account. A user can "
        "have multiple portfolios. A portfolio can be single or joint. If "
        "`onboarding_form_status` is 13, the user can invest in mutual funds. Else the "
        "account is not active.\n\n"
        "**If you see session errors, connection issues, or tool calls fail unexpectedly, "
        "tell the user to restart Claude Desktop. This can happen after the server has restarted "
        "and the client holds a stale session.**"
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "token": {"type": "string", "description": "Kuvera session JWT token"},
        },
        "required": ["token"],
    },
)

TOOL_GET_PORTFOLIO_PERFORMANCE = types.Tool(
    name="getPortfolioPerformance",
    description=(
        "Get performance data for all user portfolios. Requires a valid token.\n\n"
        "**If you see session errors, connection issues, or tool calls fail unexpectedly, "
        "tell the user to restart Claude Desktop. This can happen after the server has restarted "
        "and the client holds a stale session.**"
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "token": {"type": "string", "description": "Kuvera session JWT token"},
        },
        "required": ["token"],
    },
)

TOOL_SWITCH_PORTFOLIO = types.Tool(
    name="switchPortfolio",
    description=(
        "Switch the current active portfolio to a different portfolio. After switching, "
        "the `current_portfolio` in account information updates and all subsequent "
        "operations reflect the new portfolio context.\n\n"
        "**If you see session errors, connection issues, or tool calls fail unexpectedly, "
        "tell the user to restart Claude Desktop. This can happen after the server has restarted "
        "and the client holds a stale session.**"
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "portfolioId": {
                "type": "string",
                "description": "Numeric portfolio ID to switch to",
            },
            "token": {"type": "string", "description": "Kuvera session JWT token"},
        },
        "required": ["portfolioId", "token"],
    },
)


def _content(text: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}]}


async def handle_get_portfolios(
    arguments: dict[str, Any], client: KuveraClient
) -> dict[str, Any]:
    token = arguments.get("token", "")
    if not KuveraClient.validate_jwt_format(token):
        return _content("Error: Invalid token format. Please provide a valid Kuvera JWT token.")
    portfolios = await client.get_portfolios(token)
    return _content(json.dumps(portfolios))


async def handle_get_portfolio_performance(
    arguments: dict[str, Any], client: KuveraClient
) -> dict[str, Any]:
    token = arguments.get("token", "")
    if not KuveraClient.validate_jwt_format(token):
        return _content("Error: Invalid token format. Please provide a valid Kuvera JWT token.")
    performance = await client.get_portfolio_performance(token)
    return _content(json.dumps(performance))


async def handle_switch_portfolio(
    arguments: dict[str, Any], client: KuveraClient
) -> dict[str, Any]:
    token = arguments.get("token", "")
    portfolio_id = arguments.get("portfolioId", "")

    if not KuveraClient.validate_jwt_format(token):
        return _content("Error: Invalid token format. Please provide a valid Kuvera JWT token.")
    if not _PORTFOLIO_ID_RE.match(str(portfolio_id)):
        return _content(
            "Error: portfolioId must be a numeric string of 1–10 digits."
        )

    result = await client.switch_portfolio(str(portfolio_id), token)
    return _content(json.dumps(result))
