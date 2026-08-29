from datetime import date

import httpx
import pytest

from company_facts.config import Settings
from company_facts.tiingo_client import (
    TiingoClient,
    TiingoError,
    parse_prices,
)

PAYLOAD = [
    {
        "date": "2026-08-28T00:00:00.000Z",
        "open": 100,
        "high": 103,
        "low": 99,
        "close": 102,
        "volume": 1000,
        "adjOpen": 98,
        "adjHigh": 101,
        "adjLow": 97,
        "adjClose": 100,
        "adjVolume": 1020,
        "divCash": 0.25,
        "splitFactor": 1,
    }
]


class NoopLimiter:
    def wait(self) -> None:
        return None


def settings() -> Settings:
    return Settings(
        tiingo_api_token="test-token-123456789",
        tiingo_base_url="https://api.tiingo.test",
    )


def test_parse_price_fields_and_validation() -> None:
    prices = parse_prices(PAYLOAD)
    assert prices[0].price_date == date(2026, 8, 28)
    assert str(prices[0].adj_close) == "100"
    assert str(prices[0].dividend_cash) == "0.25"

    invalid = [{**PAYLOAD[0], "close": -1}]
    with pytest.raises(TiingoError, match="non-positive"):
        parse_prices(invalid)


def test_client_uses_header_and_retries_429() -> None:
    requests: list[httpx.Request] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json=PAYLOAD)

    client = TiingoClient(
        settings(),
        transport=httpx.MockTransport(handler),
        sleeper=sleeps.append,
        limiter=NoopLimiter(),  # type: ignore[arg-type]
    )
    try:
        prices = client.prices("BRK.B", date(2026, 8, 1), date(2026, 8, 28))
    finally:
        client.close()

    assert len(prices) == 1
    assert len(requests) == 2
    assert requests[-1].url.path == "/tiingo/daily/BRK-B/prices"
    assert requests[-1].headers["Authorization"] == "Token test-token-123456789"
    assert "token" not in requests[-1].url.params
    assert sleeps == [0]
