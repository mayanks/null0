"""
Fund tools: getFundDetails, getEquityDistribution.
"""

import json
import math
import re
from textwrap import dedent
from typing import Any

from loguru import logger

import mcp.types as types

from kuvera_client import KuveraClient

_FUND_CODE_RE = re.compile(r"^[A-Z0-9\-]{1,20}$")

TOOL_GET_FUND_DETAILS = types.Tool(
    name="getFundDetails",
    description=dedent("""\
        Get details of a mutual fund. Provide a list of fund codes and a valid token.
        Returns AUM, category, code, expense ratio, name, NAV, NAV date, returns, and
        volatility for each fund.

        **If you see session errors, connection issues, or tool calls fail unexpectedly,
        tell the user to restart Claude Desktop. This can happen after the server has restarted
        and the client holds a stale session.**
    """).strip(),
    inputSchema={
        "type": "object",
        "properties": {
            "fundCodes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of fund codes (1–20 items)",
            },
            "token": {"type": "string", "description": "Kuvera session JWT token"},
        },
        "required": ["fundCodes", "token"],
    },
)

TOOL_GET_EQUITY_DISTRIBUTION = types.Tool(
    name="getEquityDistribution",
    description=dedent("""\
        Get equity distribution in a fund for the current value of investment.
        Provide a fund code and a valid token.

        **If you see session errors, connection issues, or tool calls fail unexpectedly,
        tell the user to restart Claude Desktop. This can happen after the server has restarted
        and the client holds a stale session.**
    """).strip(),
    inputSchema={
        "type": "object",
        "properties": {
            "fundCode": {
                "type": "string",
                "description": "Fund code (uppercase alphanumeric, max 20 chars)",
            },
            "current_value": {
                "type": "number",
                "description": "Current investment value (must be finite and positive)",
            },
            "token": {"type": "string", "description": "Kuvera session JWT token"},
        },
        "required": ["fundCode", "current_value", "token"],
    },
)


def _content(text: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}]}


async def handle_get_fund_details(
    arguments: dict[str, Any], client: KuveraClient
) -> dict[str, Any]:
    token = arguments.get("token", "")
    if not KuveraClient.validate_jwt_format(token):
        return _content("Error: Invalid token format. Please provide a valid Kuvera JWT token.")

    fund_codes = arguments.get("fundCodes", [])
    if not isinstance(fund_codes, list) or len(fund_codes) < 1 or len(fund_codes) > 20:
        return _content(
            "Error: fundCodes must be a list of 1 to 20 fund codes."
        )
    for code in fund_codes:
        if not isinstance(code, str) or not _FUND_CODE_RE.match(code):
            return _content(
                f"Error: Invalid fund code '{code}'. "
                "Fund codes must be uppercase alphanumeric (with hyphens), max 20 characters."
            )

    details = await client.get_fund_details(fund_codes, token)
    if not details:
        return _content("{}")
    return _content(json.dumps(details))


async def handle_get_equity_distribution(
    arguments: dict[str, Any], client: KuveraClient
) -> dict[str, Any]:
    token = arguments.get("token", "")
    if not KuveraClient.validate_jwt_format(token):
        return _content("Error: Invalid token format. Please provide a valid Kuvera JWT token.")

    fund_code = arguments.get("fundCode", "")
    if not isinstance(fund_code, str) or not _FUND_CODE_RE.match(fund_code):
        return _content(
            "Error: Invalid fundCode. Must be uppercase alphanumeric (with hyphens), max 20 characters."
        )

    current_value = arguments.get("current_value")
    try:
        current_value = float(current_value)
    except (TypeError, ValueError):
        return _content("Error: current_value must be a finite, positive number.")
    if not math.isfinite(current_value) or current_value <= 0:
        return _content("Error: current_value must be a finite, positive number.")

    distribution = await client.get_equity_distribution(fund_code, current_value, token)
    return _content(json.dumps(distribution))
