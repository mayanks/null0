"""
Unit tests for KuveraClient — all httpx calls mocked via respx.
"""

import json
import logging
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx

from kuvera_client import KuveraClient, TokenRedactionFilter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BASE = "https://api.kuvera.in"
VALID_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"


def make_client() -> tuple[KuveraClient, httpx.AsyncClient]:
    """Return (KuveraClient, httpx.AsyncClient) pair wired to BASE."""
    http = httpx.AsyncClient(base_url=BASE)
    return KuveraClient(http), http


# ---------------------------------------------------------------------------
# validate_jwt_format
# ---------------------------------------------------------------------------


class TestValidateJwtFormat:
    def test_valid_jwt(self):
        assert KuveraClient.validate_jwt_format(VALID_TOKEN) is True

    def test_empty_string(self):
        assert KuveraClient.validate_jwt_format("") is False

    def test_whitespace_only(self):
        assert KuveraClient.validate_jwt_format("   ") is False

    def test_crlf_injection(self):
        assert KuveraClient.validate_jwt_format("aaa.bbb.ccc\r\nX-Injected: evil") is False

    def test_two_segments(self):
        assert KuveraClient.validate_jwt_format("aaa.bbb") is False

    def test_four_segments(self):
        assert KuveraClient.validate_jwt_format("aaa.bbb.ccc.ddd") is False

    def test_leading_whitespace(self):
        assert KuveraClient.validate_jwt_format(" " + VALID_TOKEN) is False

    def test_trailing_whitespace(self):
        assert KuveraClient.validate_jwt_format(VALID_TOKEN + " ") is False


# ---------------------------------------------------------------------------
# TokenRedactionFilter
# ---------------------------------------------------------------------------


class TestTokenRedactionFilter:
    def test_jwt_is_redacted_from_log(self):
        """A JWT-shaped string must not appear in log output."""
        handler = logging.handlers_list = []
        records: list[logging.LogRecord] = []

        class CapturingHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record)

        capture = CapturingHandler()
        filt = TokenRedactionFilter()
        capture.addFilter(filt)

        test_logger = logging.getLogger("test_redaction")
        test_logger.addHandler(capture)
        test_logger.setLevel(logging.DEBUG)
        test_logger.propagate = False

        try:
            # Log a message containing a JWT
            test_logger.warning("Token is %s", VALID_TOKEN)
            assert records, "Expected at least one log record"
            msg = records[0].getMessage()
            assert VALID_TOKEN not in msg, "JWT token must be redacted from log output"
            assert "[REDACTED]" in msg
        finally:
            test_logger.removeHandler(capture)

    def test_non_jwt_not_affected(self):
        """Normal log messages should pass through unchanged."""
        records: list[logging.LogRecord] = []

        class CapturingHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record)

        capture = CapturingHandler()
        filt = TokenRedactionFilter()
        capture.addFilter(filt)

        test_logger = logging.getLogger("test_redaction_plain")
        test_logger.addHandler(capture)
        test_logger.setLevel(logging.DEBUG)
        test_logger.propagate = False

        try:
            test_logger.info("Hello, world!")
            assert records[0].getMessage() == "Hello, world!"
        finally:
            test_logger.removeHandler(capture)


# ---------------------------------------------------------------------------
# get_account_info
# ---------------------------------------------------------------------------


ACCOUNT_RESPONSE = {
    "id": 1,
    "name": "John Doe",
    "email": "john@example.com",
    "onboarding_state": 13,
    "primary_portfolio_id": 42,
    "current_portfolio": {
        "id": 42,
        "name": "Main",
        "onboarding_state": 13,
        "mode_of_investment": "direct",
        "aof_status": 13,
    },
    "primary_portfolio": {
        "id": 42,
        "name": "Main",
        "onboarding_state": 13,
        "mode_of_investment": "direct",
        "aof_status": 13,
        "email": "john@example.com",
    },
}


@pytest.mark.asyncio
async def test_get_account_info_happy_path():
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/v3/user/info.json").mock(
            return_value=httpx.Response(200, json=ACCOUNT_RESPONSE)
        )
        client, http = make_client()
        async with http:
            result = await client.get_account_info(VALID_TOKEN)
    assert result is not None
    assert result["name"] == "John Doe"
    assert result["current_portfolio"]["id"] == 42
    assert result["primary_portfolio"]["email"] == "john@example.com"


@pytest.mark.asyncio
async def test_get_account_info_401():
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/v3/user/info.json").mock(
            return_value=httpx.Response(401)
        )
        client, http = make_client()
        async with http:
            result = await client.get_account_info(VALID_TOKEN)
    assert result is None


@pytest.mark.asyncio
async def test_get_account_info_500():
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/v3/user/info.json").mock(
            return_value=httpx.Response(500)
        )
        client, http = make_client()
        async with http:
            result = await client.get_account_info(VALID_TOKEN)
    assert result is None


@pytest.mark.asyncio
async def test_get_account_info_timeout():
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/v3/user/info.json").mock(
            side_effect=httpx.TimeoutException("timeout")
        )
        client, http = make_client()
        async with http:
            result = await client.get_account_info(VALID_TOKEN)
    assert result is None


# ---------------------------------------------------------------------------
# get_portfolios
# ---------------------------------------------------------------------------

PORTFOLIOS_RESPONSE = [
    {
        "id": 10,
        "aof_status": 13,
        "portfolio_name": "Portfolio A",
        "mode_of_investment": "direct",
        "onboarding_form_state": 13,
        "portfolio_code": "ABC123",
        "primary_applicant": {
            "id": 1,
            "name": "Jane",
            "gender": "F",
            "date_of_birth": "1990-01-01",
            "marital_status": "single",
            "country_of_birth": "IN",
        },
        "secondary_applicant1": None,
        "secondary_applicant2": None,
        "nominees": [
            {"name": "Bob", "date_of_birth": "2010-05-05", "relationship": "son"}
        ],
    }
]


@pytest.mark.asyncio
async def test_get_portfolios_happy_path():
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/users_service/v5/portfolio.json").mock(
            return_value=httpx.Response(200, json=PORTFOLIOS_RESPONSE)
        )
        client, http = make_client()
        async with http:
            result = await client.get_portfolios(VALID_TOKEN)
    assert len(result) == 1
    assert result[0]["portfolio_id"] == 10
    assert len(result[0]["applicants"]) == 1
    assert result[0]["nominees"][0]["name"] == "Bob"


@pytest.mark.asyncio
async def test_get_portfolios_error():
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/users_service/v5/portfolio.json").mock(
            return_value=httpx.Response(500)
        )
        client, http = make_client()
        async with http:
            result = await client.get_portfolios(VALID_TOKEN)
    assert result == []


@pytest.mark.asyncio
async def test_get_portfolios_timeout():
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/users_service/v5/portfolio.json").mock(
            side_effect=httpx.TimeoutException("timeout")
        )
        client, http = make_client()
        async with http:
            result = await client.get_portfolios(VALID_TOKEN)
    assert result == []


# ---------------------------------------------------------------------------
# get_fund_details
# ---------------------------------------------------------------------------

FUND_DETAILS_RESPONSE = [
    {
        "aum": 1000000.0,
        "category": "Equity",
        "code": "FUND001",
        "expense_ratio": 1.5,
        "name": "Test Fund",
        "fund_name": "Test Fund Direct Growth",
        "nav": {"nav": 100.0, "date": "2024-01-01"},
        "returns": {"1y": 15.0},
        "volatility": 12.0,
    }
]


@pytest.mark.asyncio
async def test_get_fund_details_happy_path():
    with respx.mock(base_url=BASE) as mock:
        mock.get("/mf/api/v5/fund_schemes/FUND001.json").mock(
            return_value=httpx.Response(200, json=FUND_DETAILS_RESPONSE)
        )
        client, http = make_client()
        async with http:
            result = await client.get_fund_details(["FUND001"], VALID_TOKEN)
    assert "FUND001" in result
    assert result["FUND001"]["nav"] == 100.0
    assert result["FUND001"]["nav_date"] == "2024-01-01"


@pytest.mark.asyncio
async def test_get_fund_details_error():
    with respx.mock(base_url=BASE) as mock:
        mock.get("/mf/api/v5/fund_schemes/FUND001.json").mock(
            return_value=httpx.Response(404)
        )
        client, http = make_client()
        async with http:
            result = await client.get_fund_details(["FUND001"], VALID_TOKEN)
    assert result == {}


@pytest.mark.asyncio
async def test_get_fund_details_timeout():
    with respx.mock(base_url=BASE) as mock:
        mock.get("/mf/api/v5/fund_schemes/FUND001.json").mock(
            side_effect=httpx.TimeoutException("timeout")
        )
        client, http = make_client()
        async with http:
            result = await client.get_fund_details(["FUND001"], VALID_TOKEN)
    assert result == {}


# ---------------------------------------------------------------------------
# get_holdings
# ---------------------------------------------------------------------------

HOLDINGS_RESPONSE = {
    "FUND001": [
        {"folioNumber": "123456/01", "units": 100.0, "allottedAmount": 9000.0}
    ]
}


@pytest.mark.asyncio
async def test_get_holdings_happy_path():
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/v3/portfolio/holdings.json").mock(
            return_value=httpx.Response(200, json=HOLDINGS_RESPONSE)
        )
        mock.get("/mf/api/v5/fund_schemes/FUND001.json").mock(
            return_value=httpx.Response(200, json=FUND_DETAILS_RESPONSE)
        )
        client, http = make_client()
        async with http:
            result = await client.get_holdings(VALID_TOKEN)
    assert len(result) == 1
    assert result[0]["code"] == "FUND001"
    assert result[0]["units"] == 100.0
    assert result[0]["current_value"] == 100.0 * 100.0  # units * nav


@pytest.mark.asyncio
async def test_get_holdings_step1_error():
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/v3/portfolio/holdings.json").mock(
            return_value=httpx.Response(500)
        )
        client, http = make_client()
        async with http:
            result = await client.get_holdings(VALID_TOKEN)
    assert result == []


@pytest.mark.asyncio
async def test_get_holdings_timeout():
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/v3/portfolio/holdings.json").mock(
            side_effect=httpx.TimeoutException("timeout")
        )
        client, http = make_client()
        async with http:
            result = await client.get_holdings(VALID_TOKEN)
    assert result == []


# ---------------------------------------------------------------------------
# get_equity_distribution
# ---------------------------------------------------------------------------

EQUITY_DIST_RESPONSE = {
    "FUND001": {
        "top_holdings": [
            {
                "security_asset_class": "Equity",
                "portfolio_date": "2024-01-01",
                "company_name": "ACME Corp",
                "percentage_to_aum": 5.0,
                "ticker": "ACME",
            },
            {
                "security_asset_class": "Debt",
                "portfolio_date": "2024-01-01",
                "company_name": "Bond Fund",
                "percentage_to_aum": 2.0,
                "ticker": "BOND",
            },
        ]
    }
}


@pytest.mark.asyncio
async def test_get_equity_distribution_happy_path():
    with respx.mock(base_url=BASE) as mock:
        mock.get("/mf/api/v5/fund_investment_stats/FUND001.json").mock(
            return_value=httpx.Response(200, json=EQUITY_DIST_RESPONSE)
        )
        client, http = make_client()
        async with http:
            result = await client.get_equity_distribution("FUND001", 10000.0, VALID_TOKEN)
    assert len(result) == 1  # Only Equity entries
    assert result[0]["company_name"] == "ACME Corp"
    assert result[0]["proportionate_amount"] == pytest.approx(500.0)


@pytest.mark.asyncio
async def test_get_equity_distribution_error():
    with respx.mock(base_url=BASE) as mock:
        mock.get("/mf/api/v5/fund_investment_stats/FUND001.json").mock(
            return_value=httpx.Response(500)
        )
        client, http = make_client()
        async with http:
            result = await client.get_equity_distribution("FUND001", 10000.0, VALID_TOKEN)
    assert result == []


@pytest.mark.asyncio
async def test_get_equity_distribution_timeout():
    with respx.mock(base_url=BASE) as mock:
        mock.get("/mf/api/v5/fund_investment_stats/FUND001.json").mock(
            side_effect=httpx.TimeoutException("timeout")
        )
        client, http = make_client()
        async with http:
            result = await client.get_equity_distribution("FUND001", 10000.0, VALID_TOKEN)
    assert result == []


# ---------------------------------------------------------------------------
# get_portfolio_performance
# ---------------------------------------------------------------------------

PERF_RESPONSE = {
    "status": "success",
    "data": {
        "42": {
            "current_value": 100000.0,
            "current_gain": 10000.0,
            "current_gain_percent": 11.0,
            "one_day_gain": 100.0,
            "one_day_gain_percent": 0.1,
            "invested": 90000.0,
            "current_xirr": 15.0,
            "alltime_xirr": 14.0,
            "alltime_return": 20000.0,
            "alltime_abs_percentage": 22.2,
            "alltime_abs_return": 20000.0,
            "portfolio_type": "self",
            "mutual_funds": [],
        }
    },
}


@pytest.mark.asyncio
async def test_get_portfolio_performance_happy_path():
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/v3/user/portfolio_performance.json").mock(
            return_value=httpx.Response(200, json=PERF_RESPONSE)
        )
        client, http = make_client()
        async with http:
            result = await client.get_portfolio_performance(VALID_TOKEN)
    assert len(result) == 1
    assert result[0]["portfolio_id"] == 42
    assert result[0]["current_value"] == 100000.0


@pytest.mark.asyncio
async def test_get_portfolio_performance_bad_status():
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/v3/user/portfolio_performance.json").mock(
            return_value=httpx.Response(200, json={"status": "error"})
        )
        client, http = make_client()
        async with http:
            result = await client.get_portfolio_performance(VALID_TOKEN)
    assert result == []


@pytest.mark.asyncio
async def test_get_portfolio_performance_timeout():
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/v3/user/portfolio_performance.json").mock(
            side_effect=httpx.TimeoutException("timeout")
        )
        client, http = make_client()
        async with http:
            result = await client.get_portfolio_performance(VALID_TOKEN)
    assert result == []


# ---------------------------------------------------------------------------
# switch_portfolio
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_switch_portfolio_success():
    with respx.mock(base_url=BASE) as mock:
        mock.post("/api/v3/portfolio/switch/42.json").mock(
            return_value=httpx.Response(200, json={"result": "ok"})
        )
        client, http = make_client()
        async with http:
            result = await client.switch_portfolio("42", VALID_TOKEN)
    assert result["success"] is True
    assert result["data"] == {"result": "ok"}


@pytest.mark.asyncio
async def test_switch_portfolio_http_error():
    with respx.mock(base_url=BASE) as mock:
        mock.post("/api/v3/portfolio/switch/42.json").mock(
            return_value=httpx.Response(403)
        )
        client, http = make_client()
        async with http:
            result = await client.switch_portfolio("42", VALID_TOKEN)
    assert result["success"] is False
    assert "403" in result["error"]


@pytest.mark.asyncio
async def test_switch_portfolio_network_error():
    with respx.mock(base_url=BASE) as mock:
        mock.post("/api/v3/portfolio/switch/42.json").mock(
            side_effect=httpx.NetworkError("connection refused")
        )
        client, http = make_client()
        async with http:
            result = await client.switch_portfolio("42", VALID_TOKEN)
    assert result["success"] is False
    assert result["error"] == "Request failed"
