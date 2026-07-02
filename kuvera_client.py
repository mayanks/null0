"""
Kuvera API client — all httpx calls are centralised here.
No tool module may import httpx directly.
"""

import base64
import datetime
import json
import logging
import math
import re
import urllib.parse
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Token redaction — must be imported early and applied to the root logger
# ---------------------------------------------------------------------------

JWT_PATTERN = re.compile(
    r"[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"
)


class TokenRedactionFilter(logging.Filter):
    """Scrub JWT-shaped strings from log records before any handler writes them.

    Handles both pre-formatted messages and lazy %-style formatting where
    the JWT may appear in record.args rather than (or in addition to) record.msg.
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        # Redact in the format string
        record.msg = JWT_PATTERN.sub("[REDACTED]", str(record.msg))
        # Redact in positional args (handles logger.warning("... %s", token))
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: JWT_PATTERN.sub("[REDACTED]", str(v)) if isinstance(v, str) else v
                    for k, v in record.args.items()
                }
            elif isinstance(record.args, (list, tuple)):
                redacted = tuple(
                    JWT_PATTERN.sub("[REDACTED]", str(a)) if isinstance(a, str) else a
                    for a in record.args
                )
                record.args = redacted
        # Redact from already-formatted exception text
        if record.exc_text:
            record.exc_text = JWT_PATTERN.sub("[REDACTED]", record.exc_text)
        return True


# ---------------------------------------------------------------------------
# KuveraClient
# ---------------------------------------------------------------------------

_JWT_RE = re.compile(
    r"^[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+$"
)


class KuveraClient:
    """Async client for the Kuvera API.

    Accepts a shared httpx.AsyncClient via constructor injection so tests can
    swap in a mock client without starting a real server.
    """

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def decode_jwt_payload(token: str) -> dict[str, Any] | None:
        """Decode the JWT payload without verifying the signature.

        Returns the claims dict, or None if the token is malformed.
        """
        try:
            payload_b64 = token.split(".")[1]
            # base64url — pad to a multiple of 4
            padded = payload_b64 + "=" * (-len(payload_b64) % 4)
            return json.loads(base64.urlsafe_b64decode(padded))
        except Exception:
            return None

    @staticmethod
    def validate_jwt_format(token: str) -> bool:
        """Return True iff *token* looks structurally like a JWT.

        This is a format check only — no signature verification.
        Rejects empty strings, whitespace, CRLF injection, and tokens that
        don't have exactly three base64url segments.
        """
        if not token or not token.strip():
            return False
        # Reject any token containing whitespace or control characters
        if token != token.strip():
            return False
        if "\r" in token or "\n" in token or " " in token or "\t" in token:
            return False
        return bool(_JWT_RE.match(token))

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _headers(self, token: str) -> dict[str, str]:
        return {
            "User-Agent": "cp-app/1.0",
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # API methods
    # ------------------------------------------------------------------

    async def get_account_info(self, token: str) -> dict[str, Any] | None:
        """GET /api/v3/user/info.json"""
        try:
            response = await self._client.get(
                "/api/v3/user/info.json",
                headers=self._headers(token),
            )
            response.raise_for_status()
            data = response.json()
            return {
                "id": data.get("id"),
                "name": data.get("name"),
                "email": data.get("email"),
                "onboarding_state": data.get("onboarding_state"),
                "primary_portfolio_id": data.get("primary_portfolio_id"),
                "current_portfolio": (
                    {
                        "id": data["current_portfolio"].get("id"),
                        "name": data["current_portfolio"].get("name"),
                        "onboarding_state": data["current_portfolio"].get(
                            "onboarding_state"
                        ),
                        "mode_of_investment": data["current_portfolio"].get(
                            "mode_of_investment"
                        ),
                        "aof_status": data["current_portfolio"].get("aof_status"),
                    }
                    if data.get("current_portfolio")
                    else None
                ),
                "primary_portfolio": (
                    {
                        "id": data["primary_portfolio"].get("id"),
                        "name": data["primary_portfolio"].get("name"),
                        "onboarding_state": data["primary_portfolio"].get(
                            "onboarding_state"
                        ),
                        "mode_of_investment": data["primary_portfolio"].get(
                            "mode_of_investment"
                        ),
                        "aof_status": data["primary_portfolio"].get("aof_status"),
                        "email": data["primary_portfolio"].get("email"),
                    }
                    if data.get("primary_portfolio")
                    else None
                ),
            }
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "Kuvera API error: HTTP %s on %s",
                exc.response.status_code,
                exc.request.url.path,
            )
            return None
        except httpx.TimeoutException:
            logger.warning("Kuvera API request timed out: get_account_info")
            return None
        except httpx.HTTPError:
            logger.warning("Kuvera API request failed: get_account_info")
            return None

    async def get_portfolios(self, token: str) -> list[dict[str, Any]]:
        """GET /api/users_service/v5/portfolio.json?v=1.238.2"""
        try:
            response = await self._client.get(
                "/api/users_service/v5/portfolio.json",
                params={"v": "1.238.2"},
                headers=self._headers(token),
            )
            response.raise_for_status()
            data = response.json()
            portfolios = []
            for x in data:
                applicants = []
                for key in ("primary_applicant", "secondary_applicant1", "secondary_applicant2"):
                    applicant = x.get(key)
                    if applicant:
                        applicants.append(
                            {
                                "id": applicant.get("id"),
                                "name": applicant.get("name"),
                                "gender": applicant.get("gender"),
                                "date_of_birth": applicant.get("date_of_birth"),
                                "marital_status": applicant.get("marital_status"),
                                "country_of_birth": applicant.get("country_of_birth"),
                            }
                        )
                nominees = []
                for nominee in x.get("nominees") or []:
                    nominees.append(
                        {
                            "name": nominee.get("name"),
                            "date_of_birth": nominee.get("date_of_birth"),
                            "relationship": nominee.get("relationship"),
                        }
                    )
                portfolios.append(
                    {
                        "portfolio_id": x.get("id"),
                        "account_status": x.get("aof_status"),
                        "portfolio_name": x.get("portfolio_name"),
                        "mode_of_investment": x.get("mode_of_investment"),
                        "onboarding_form_state": x.get("onboarding_form_state"),
                        "portfolio_code": x.get("portfolio_code"),
                        "applicants": applicants,
                        "nominees": nominees,
                    }
                )
            return portfolios
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "Kuvera API error: HTTP %s on %s",
                exc.response.status_code,
                exc.request.url.path,
            )
            return []
        except httpx.TimeoutException:
            logger.warning("Kuvera API request timed out: get_portfolios")
            return []
        except httpx.HTTPError:
            logger.warning("Kuvera API request failed: get_portfolios")
            return []

    async def get_fund_details(
        self, fund_codes: list[str], token: str
    ) -> dict[str, Any]:
        """GET /mf/api/v5/fund_schemes/{codes}.json"""
        codes = urllib.parse.quote("|".join(fund_codes), safe="")
        try:
            response = await self._client.get(
                f"/mf/api/v5/fund_schemes/{codes}.json",
                headers=self._headers(token),
            )
            response.raise_for_status()
            data = response.json()
            result: dict[str, Any] = {}
            for big_fund in data:
                fund = {
                    "aum": big_fund.get("aum"),
                    "category": big_fund.get("category"),
                    "code": big_fund.get("code"),
                    "expense_ratio": big_fund.get("expense_ratio"),
                    "name": big_fund.get("name"),
                    "fund_name": big_fund.get("fund_name"),
                    "nav": (big_fund.get("nav") or {}).get("nav"),
                    "nav_date": (big_fund.get("nav") or {}).get("date"),
                    "returns": big_fund.get("returns"),
                    "volatility": big_fund.get("volatility"),
                }
                if fund["code"]:
                    result[fund["code"]] = fund
            return result
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "Kuvera API error: HTTP %s on %s",
                exc.response.status_code,
                exc.request.url.path,
            )
            return {}
        except httpx.TimeoutException:
            logger.warning("Kuvera API request timed out: get_fund_details")
            return {}
        except httpx.HTTPError:
            logger.warning("Kuvera API request failed: get_fund_details")
            return {}

    async def get_holdings(self, token: str) -> list[dict[str, Any]]:
        """Two sequential calls: holdings then fund details."""
        try:
            response = await self._client.get(
                "/api/v3/portfolio/holdings.json",
                params={"v": "1.238.2"},
                headers=self._headers(token),
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "Kuvera API error: HTTP %s on %s",
                exc.response.status_code,
                exc.request.url.path,
            )
            return []
        except httpx.TimeoutException:
            logger.warning("Kuvera API request timed out: get_holdings (step 1)")
            return []
        except httpx.HTTPError:
            logger.warning("Kuvera API request failed: get_holdings (step 1)")
            return []

        fund_codes = list(data.keys())
        if not fund_codes:
            return []

        fund_details = await self.get_fund_details(fund_codes, token)

        holdings: list[dict[str, Any]] = []
        for fund_code in fund_codes:
            detail = fund_details.get(fund_code, {})
            nav = (detail.get("nav") or 0.0) if detail else 0.0
            for x in data.get(fund_code, []):
                units = x.get("units", 0.0) or 0.0
                holdings.append(
                    {
                        "code": fund_code,
                        "folio_number": x.get("folioNumber", "Unknown"),
                        "units": units,
                        "invested_value": x.get("allottedAmount", 0.0),
                        "current_value": units * nav,
                        "fund_details": detail,
                    }
                )
        return holdings

    async def get_equity_distribution(
        self, fund_code: str, current_value: float, token: str
    ) -> list[dict[str, Any]]:
        """GET /mf/api/v5/fund_investment_stats/{fund_code}.json"""
        encoded_code = urllib.parse.quote(fund_code, safe="")
        try:
            response = await self._client.get(
                f"/mf/api/v5/fund_investment_stats/{encoded_code}.json",
                headers=self._headers(token),
            )
            response.raise_for_status()
            data = response.json()
            fund_data = data.get(fund_code, {})
            top_holdings = fund_data.get("top_holdings", []) or []
            return [
                {
                    "portfolio_date": h.get("portfolio_date"),
                    "company_name": h.get("company_name"),
                    "percentage_to_aum": h.get("percentage_to_aum"),
                    "ticker": h.get("ticker"),
                    "proportionate_amount": (
                        (h.get("percentage_to_aum") or 0.0) * current_value / 100
                    ),
                }
                for h in top_holdings
                if h.get("security_asset_class") == "Equity"
            ]
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "Kuvera API error: HTTP %s on %s",
                exc.response.status_code,
                exc.request.url.path,
            )
            return []
        except httpx.TimeoutException:
            logger.warning("Kuvera API request timed out: get_equity_distribution")
            return []
        except httpx.HTTPError:
            logger.warning("Kuvera API request failed: get_equity_distribution")
            return []

    async def get_portfolio_performance(self, token: str) -> list[dict[str, Any]]:
        """GET /api/v3/user/portfolio_performance.json?v=1.239.2"""
        try:
            response = await self._client.get(
                "/api/v3/user/portfolio_performance.json",
                params={"v": "1.239.2"},
                headers=self._headers(token),
            )
            response.raise_for_status()
            result = response.json()
            if result.get("status") != "success" or not result.get("data"):
                return []
            return [
                {
                    "portfolio_id": int(portfolio_id),
                    "current_value": perf.get("current_value"),
                    "current_gain": perf.get("current_gain"),
                    "current_gain_percent": perf.get("current_gain_percent"),
                    "one_day_gain": perf.get("one_day_gain"),
                    "one_day_gain_percent": perf.get("one_day_gain_percent"),
                    "invested": perf.get("invested"),
                    "current_xirr": perf.get("current_xirr"),
                    "alltime_xirr": perf.get("alltime_xirr"),
                    "alltime_return": perf.get("alltime_return"),
                    "alltime_abs_percentage": perf.get("alltime_abs_percentage"),
                    "alltime_abs_return": perf.get("alltime_abs_return"),
                    "portfolio_type": perf.get("portfolio_type"),
                    "mutual_funds": perf.get("mutual_funds"),
                }
                for portfolio_id, perf in result["data"].items()
            ]
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "Kuvera API error: HTTP %s on %s",
                exc.response.status_code,
                exc.request.url.path,
            )
            return []
        except httpx.TimeoutException:
            logger.warning("Kuvera API request timed out: get_portfolio_performance")
            return []
        except httpx.HTTPError:
            logger.warning("Kuvera API request failed: get_portfolio_performance")
            return []

    async def switch_portfolio(
        self, portfolio_id: str, token: str
    ) -> dict[str, Any]:
        """POST /api/v3/portfolio/switch/{portfolio_id}.json?v=1.239.1"""
        try:
            response = await self._client.post(
                f"/api/v3/portfolio/switch/{portfolio_id}.json",
                params={"v": "1.239.1"},
                headers=self._headers(token),
                content=b"",
            )
            response.raise_for_status()
            return {"success": True, "data": response.json()}
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "Kuvera API error: HTTP %s on %s",
                exc.response.status_code,
                exc.request.url.path,
            )
            return {"success": False, "error": f"HTTP {exc.response.status_code}"}
        except httpx.TimeoutException:
            logger.warning("Kuvera API request timed out: switch_portfolio")
            return {"success": False, "error": "Request failed"}
        except httpx.HTTPError:
            logger.warning("Kuvera API request failed: switch_portfolio")
            return {"success": False, "error": "Request failed"}
