"""
Account tools: validateToken, getAccountInformation.
"""

import json
from typing import Any

from loguru import logger

import mcp.server.lowlevel
import mcp.types as types

from kuvera_client import KuveraClient



def register(server: mcp.server.lowlevel.Server, client: KuveraClient) -> None:
    """Register account tools on *server*."""

    @server.list_tools()
    async def _list_tools_account() -> list[types.Tool]:
        # This will be overridden by the combined list_tools handler in server.py
        return []

    # We use call_tool dispatch — actual registration is in the combined handler.
    # Store tools metadata for discovery.
    pass


# ---------------------------------------------------------------------------
# Tool handlers (called directly from server.py's call_tool dispatcher)
# ---------------------------------------------------------------------------

TOOL_VALIDATE_TOKEN = types.Tool(
    name="validateToken",
    description=(
        "Validate if the token is valid. You need to validate the token before using "
        "any other tool. Ask the user to get the token after logging in to Kuvera on a "
        "browser and then get the token from the console using "
        "`localStorage.getItem('vue-authenticate.vueauth_token')`. If the user provides "
        "a wrong token, ask the user to provide the correct token.\n\n"
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

TOOL_GET_ACCOUNT_INFORMATION = types.Tool(
    name="getAccountInformation",
    description=(
        "Get user account information with portfolio details. Requires a valid token.\n"
        "These are high level information which provides user information, their current "
        "portfolio and their primary portfolio.\n\n"
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


def _content(text: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}]}


async def handle_validate_token(
    arguments: dict[str, Any], client: KuveraClient
) -> dict[str, Any]:
    token = arguments.get("token", "")
    if not KuveraClient.validate_jwt_format(token):
        return _content("Error: Invalid token format. Please provide a valid Kuvera JWT token.")

    payload = KuveraClient.decode_jwt_payload(token)
    if payload:
        logger.info("JWT payload: {}", json.dumps(payload))

    account = await client.get_account_info(token)
    return _content("true" if account else "false")


async def handle_get_account_information(
    arguments: dict[str, Any], client: KuveraClient
) -> dict[str, Any]:
    token = arguments.get("token", "")
    if not KuveraClient.validate_jwt_format(token):
        return _content("Error: Invalid token format. Please provide a valid Kuvera JWT token.")
    account = await client.get_account_info(token)
    if not account:
        return _content("{}")
    return _content(json.dumps(account))
