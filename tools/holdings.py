"""
Holdings tool: getHoldings.
"""

import json
from textwrap import dedent
from typing import Any

from loguru import logger

import mcp.types as types

from kuvera_client import KuveraClient

TOOL_GET_HOLDINGS = types.Tool(
    name="getHoldings",
    description=dedent("""\
        Get list of all mutual funds in which the user has invested. Requires a valid token.
        Each holding includes fund code, folio, units, invested and current value
        (units × NAV), plan type, lock-free units, category, SIP status, and fund details.

        Return fields (array of):
        - code : unique identifier of a mutual fund
        - folio_number : unique identifier of a folio. A user may have multiple folios for the same fund. We should merge those entries into a single entry.
        - units : number of units held
        - direct_plan : boolean indicating if the plan is a direct plan
        - lock_free_units : number of units that are not locked. These are the units user can sell immediately.
        - invested_value : total amount invested in the fund. This is net of all purchases and redemptions.
        - current_value : current value of the investment in this fund (units × NAV)
        - fund_details : details of the fund (AUM, category, expense ratio, name, NAV, NAV date, returns, volatility)
        - sip_running (bool): boolean indicating if a SIP is running for this fund
        - category : category of the fund. Valid values are: "Equity", "Debt", "Hybrid", "Other".
        - sips (optional): present only when active SIPs exist. Array of objects with
          - amount : amount of the SIP
          - order_date : date on which this SIP order was placed
          - frequency : frequency of the SIP. Valid values are: "Monthly", "Weekly".
          - start_date : If frequency is Monthly, then just pick the date part of the start_date. If frequency is Weekly, then pick the day of the week from the start_date.

        **If you see session errors, connection issues, or tool calls fail unexpectedly,
        tell the user to restart Claude Desktop. This can happen after the server has restarted
        and the client holds a stale session.**
    """).strip(),
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
