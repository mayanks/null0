"""
Tool-level tests — KuveraClient is mocked.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kuvera_client import KuveraClient
from tools.account import handle_get_account_information, handle_validate_token
from tools.funds import handle_get_equity_distribution, handle_get_fund_details
from tools.holdings import handle_get_holdings
from tools.portfolio import (
    handle_get_portfolio_performance,
    handle_get_portfolios,
    handle_switch_portfolio,
)

# A structurally valid token for format-check tests
VALID_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
INVALID_TOKEN = "not-a-valid-jwt"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _text(result: dict) -> str:
    """Extract the text from a tool content result."""
    return result["content"][0]["text"]


def _assert_content_shape(result: dict) -> None:
    assert "content" in result
    assert isinstance(result["content"], list)
    assert len(result["content"]) >= 1
    assert result["content"][0]["type"] == "text"
    assert isinstance(result["content"][0]["text"], str)


def mock_client(**kwargs) -> MagicMock:
    """Return a MagicMock KuveraClient with async methods."""
    client = MagicMock(spec=KuveraClient)
    for method, return_value in kwargs.items():
        setattr(client, method, AsyncMock(return_value=return_value))
    return client


# ---------------------------------------------------------------------------
# validateToken
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validate_token_valid():
    client = mock_client(
        get_account_info={"id": 1, "name": "Jane"}
    )
    result = await handle_validate_token({"token": VALID_TOKEN}, client)
    _assert_content_shape(result)
    assert _text(result) == "true"


@pytest.mark.asyncio
async def test_validate_token_invalid_from_api():
    client = mock_client(get_account_info=None)
    result = await handle_validate_token({"token": VALID_TOKEN}, client)
    _assert_content_shape(result)
    assert _text(result) == "false"


@pytest.mark.asyncio
async def test_validate_token_bad_format():
    client = mock_client()
    result = await handle_validate_token({"token": INVALID_TOKEN}, client)
    _assert_content_shape(result)
    assert _text(result).startswith("Error:")
    # No API call should be made
    client.get_account_info.assert_not_called()


# ---------------------------------------------------------------------------
# getAccountInformation
# ---------------------------------------------------------------------------

ACCOUNT_DATA = {
    "id": 1,
    "name": "John",
    "email": "j@example.com",
    "onboarding_state": 13,
    "primary_portfolio_id": 5,
    "current_portfolio": {"id": 5, "name": "Main"},
    "primary_portfolio": {"id": 5, "name": "Main", "email": "j@example.com"},
}


@pytest.mark.asyncio
async def test_get_account_information_happy():
    client = mock_client(get_account_info=ACCOUNT_DATA)
    result = await handle_get_account_information({"token": VALID_TOKEN}, client)
    _assert_content_shape(result)
    parsed = json.loads(_text(result))
    assert parsed["name"] == "John"


@pytest.mark.asyncio
async def test_get_account_information_error():
    client = mock_client(get_account_info=None)
    result = await handle_get_account_information({"token": VALID_TOKEN}, client)
    _assert_content_shape(result)
    assert _text(result) == "{}"


@pytest.mark.asyncio
async def test_get_account_information_invalid_token():
    client = mock_client()
    result = await handle_get_account_information({"token": INVALID_TOKEN}, client)
    _assert_content_shape(result)
    assert _text(result).startswith("Error:")


# ---------------------------------------------------------------------------
# getPortfolios
# ---------------------------------------------------------------------------

PORTFOLIOS_DATA = [
    {
        "portfolio_id": 10,
        "account_status": 13,
        "portfolio_name": "My Portfolio",
        "mode_of_investment": "direct",
        "onboarding_form_state": 13,
        "portfolio_code": "ABC",
        "applicants": [],
        "nominees": [],
    }
]


@pytest.mark.asyncio
async def test_get_portfolios_happy():
    client = mock_client(get_portfolios=PORTFOLIOS_DATA)
    result = await handle_get_portfolios({"token": VALID_TOKEN}, client)
    _assert_content_shape(result)
    parsed = json.loads(_text(result))
    assert len(parsed) == 1
    assert parsed[0]["portfolio_id"] == 10


@pytest.mark.asyncio
async def test_get_portfolios_error():
    client = mock_client(get_portfolios=[])
    result = await handle_get_portfolios({"token": VALID_TOKEN}, client)
    _assert_content_shape(result)
    parsed = json.loads(_text(result))
    assert parsed == []


@pytest.mark.asyncio
async def test_get_portfolios_invalid_token():
    client = mock_client()
    result = await handle_get_portfolios({"token": INVALID_TOKEN}, client)
    _assert_content_shape(result)
    assert _text(result).startswith("Error:")


# ---------------------------------------------------------------------------
# getPortfolioPerformance
# ---------------------------------------------------------------------------

PERF_DATA = [
    {
        "portfolio_id": 42,
        "current_value": 100000.0,
        "current_gain": 10000.0,
        "current_gain_percent": 11.0,
    }
]


@pytest.mark.asyncio
async def test_get_portfolio_performance_happy():
    client = mock_client(get_portfolio_performance=PERF_DATA)
    result = await handle_get_portfolio_performance({"token": VALID_TOKEN}, client)
    _assert_content_shape(result)
    parsed = json.loads(_text(result))
    assert parsed[0]["portfolio_id"] == 42


@pytest.mark.asyncio
async def test_get_portfolio_performance_error():
    client = mock_client(get_portfolio_performance=[])
    result = await handle_get_portfolio_performance({"token": VALID_TOKEN}, client)
    _assert_content_shape(result)
    parsed = json.loads(_text(result))
    assert parsed == []


# ---------------------------------------------------------------------------
# switchPortfolio
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_switch_portfolio_happy():
    client = mock_client(switch_portfolio={"success": True, "data": {}})
    result = await handle_switch_portfolio(
        {"portfolioId": "42", "token": VALID_TOKEN}, client
    )
    _assert_content_shape(result)
    parsed = json.loads(_text(result))
    assert parsed["success"] is True


@pytest.mark.asyncio
async def test_switch_portfolio_invalid_portfolio_id():
    client = mock_client()
    result = await handle_switch_portfolio(
        {"portfolioId": "not-a-number", "token": VALID_TOKEN}, client
    )
    _assert_content_shape(result)
    assert _text(result).startswith("Error:")
    client.switch_portfolio.assert_not_called()


@pytest.mark.asyncio
async def test_switch_portfolio_invalid_token():
    client = mock_client()
    result = await handle_switch_portfolio(
        {"portfolioId": "42", "token": INVALID_TOKEN}, client
    )
    _assert_content_shape(result)
    assert _text(result).startswith("Error:")


# ---------------------------------------------------------------------------
# getHoldings
# ---------------------------------------------------------------------------

HOLDINGS_DATA = [
    {
        "code": "FUND001",
        "folio_number": "123456",
        "units": 100.0,
        "invested_value": 9000.0,
        "current_value": 10000.0,
        "fund_details": {},
    }
]


@pytest.mark.asyncio
async def test_get_holdings_happy():
    client = mock_client(get_holdings=HOLDINGS_DATA)
    result = await handle_get_holdings({"token": VALID_TOKEN}, client)
    _assert_content_shape(result)
    parsed = json.loads(_text(result))
    assert len(parsed) == 1
    assert parsed[0]["code"] == "FUND001"


@pytest.mark.asyncio
async def test_get_holdings_error():
    client = mock_client(get_holdings=[])
    result = await handle_get_holdings({"token": VALID_TOKEN}, client)
    _assert_content_shape(result)
    parsed = json.loads(_text(result))
    assert parsed == []


@pytest.mark.asyncio
async def test_get_holdings_invalid_token():
    client = mock_client()
    result = await handle_get_holdings({"token": INVALID_TOKEN}, client)
    _assert_content_shape(result)
    assert _text(result).startswith("Error:")


# ---------------------------------------------------------------------------
# getFundDetails
# ---------------------------------------------------------------------------

FUND_DETAILS_DATA = {
    "FUND001": {
        "aum": 1000000.0,
        "category": "Equity",
        "code": "FUND001",
        "nav": 100.0,
    }
}


@pytest.mark.asyncio
async def test_get_fund_details_happy():
    client = mock_client(get_fund_details=FUND_DETAILS_DATA)
    result = await handle_get_fund_details(
        {"fundCodes": ["FUND001"], "token": VALID_TOKEN}, client
    )
    _assert_content_shape(result)
    parsed = json.loads(_text(result))
    assert "FUND001" in parsed


@pytest.mark.asyncio
async def test_get_fund_details_error():
    client = mock_client(get_fund_details={})
    result = await handle_get_fund_details(
        {"fundCodes": ["FUND001"], "token": VALID_TOKEN}, client
    )
    _assert_content_shape(result)
    assert _text(result) == "{}"


@pytest.mark.asyncio
async def test_get_fund_details_21_codes():
    """21 fund codes must return an error without making any API call."""
    client = mock_client()
    codes = [f"FUND{i:03d}" for i in range(21)]
    result = await handle_get_fund_details(
        {"fundCodes": codes, "token": VALID_TOKEN}, client
    )
    _assert_content_shape(result)
    assert _text(result).startswith("Error:")
    client.get_fund_details.assert_not_called()


@pytest.mark.asyncio
async def test_get_fund_details_invalid_code_format():
    """Lowercase fund code should be rejected."""
    client = mock_client()
    result = await handle_get_fund_details(
        {"fundCodes": ["invalid_code!"], "token": VALID_TOKEN}, client
    )
    _assert_content_shape(result)
    assert _text(result).startswith("Error:")
    client.get_fund_details.assert_not_called()


@pytest.mark.asyncio
async def test_get_fund_details_invalid_token():
    client = mock_client()
    result = await handle_get_fund_details(
        {"fundCodes": ["FUND001"], "token": INVALID_TOKEN}, client
    )
    _assert_content_shape(result)
    assert _text(result).startswith("Error:")


# ---------------------------------------------------------------------------
# getEquityDistribution
# ---------------------------------------------------------------------------

EQUITY_DATA = [
    {
        "portfolio_date": "2024-01-01",
        "company_name": "ACME",
        "percentage_to_aum": 5.0,
        "ticker": "ACME",
        "proportionate_amount": 500.0,
    }
]


@pytest.mark.asyncio
async def test_get_equity_distribution_happy():
    client = mock_client(get_equity_distribution=EQUITY_DATA)
    result = await handle_get_equity_distribution(
        {"fundCode": "FUND001", "current_value": 10000.0, "token": VALID_TOKEN}, client
    )
    _assert_content_shape(result)
    parsed = json.loads(_text(result))
    assert len(parsed) == 1
    assert parsed[0]["company_name"] == "ACME"


@pytest.mark.asyncio
async def test_get_equity_distribution_error():
    client = mock_client(get_equity_distribution=[])
    result = await handle_get_equity_distribution(
        {"fundCode": "FUND001", "current_value": 10000.0, "token": VALID_TOKEN}, client
    )
    _assert_content_shape(result)
    parsed = json.loads(_text(result))
    assert parsed == []


@pytest.mark.asyncio
async def test_get_equity_distribution_negative_value():
    client = mock_client()
    result = await handle_get_equity_distribution(
        {"fundCode": "FUND001", "current_value": -100.0, "token": VALID_TOKEN}, client
    )
    _assert_content_shape(result)
    assert _text(result).startswith("Error:")
    client.get_equity_distribution.assert_not_called()


@pytest.mark.asyncio
async def test_get_equity_distribution_zero_value():
    client = mock_client()
    result = await handle_get_equity_distribution(
        {"fundCode": "FUND001", "current_value": 0.0, "token": VALID_TOKEN}, client
    )
    _assert_content_shape(result)
    assert _text(result).startswith("Error:")
    client.get_equity_distribution.assert_not_called()


@pytest.mark.asyncio
async def test_get_equity_distribution_invalid_fund_code():
    client = mock_client()
    result = await handle_get_equity_distribution(
        {"fundCode": "invalid!", "current_value": 100.0, "token": VALID_TOKEN}, client
    )
    _assert_content_shape(result)
    assert _text(result).startswith("Error:")
    client.get_equity_distribution.assert_not_called()


@pytest.mark.asyncio
async def test_get_equity_distribution_invalid_token():
    client = mock_client()
    result = await handle_get_equity_distribution(
        {"fundCode": "FUND001", "current_value": 100.0, "token": INVALID_TOKEN}, client
    )
    _assert_content_shape(result)
    assert _text(result).startswith("Error:")
