"""
Holdings tool: getHoldings.
"""

import json
import logging
from typing import Any

import mcp.types as types

from kuvera_client import KuveraClient

logger = logging.getLogger(__name__)

TOOL_GET_HOLDINGS = types.Tool(
    name="getHoldings",
    description=(
        "Get list of all mutual funds in which the user has invested. Each holding has "
        "name, amount, invested value, and current value (units × NAV). Requires a valid token."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "token": {"type": "string", "description": "Kuvera session JWT token"},
        },
        "required": ["token"],
    },
)


def _content(text: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}]}


async def handle_get_holdings(
    arguments: dict[str, Any], client: KuveraClient
) -> dict[str, Any]:
    token = arguments.get("token", "")
    if not KuveraClient.validate_jwt_format(token):
        return _content("Error: Invalid token format. Please provide a valid Kuvera JWT token.")
    holdings = await client.get_holdings(token)
    return _content(json.dumps(holdings))
