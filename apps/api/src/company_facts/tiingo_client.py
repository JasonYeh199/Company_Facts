from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from .config import Settings, get_settings


class TiingoError(RuntimeError):
    pass


class TiingoNotConfigured(TiingoError):
    pass


class TiingoSymbolUnavailable(TiingoError):
    pass


@dataclass(frozen=True)
class TiingoPrice:
    price_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    adj_open: Decimal
    adj_high: Decimal
    adj_low: Decimal
    adj_close: Decimal
    adj_volume: Decimal
    dividend_cash: Decimal
    split_factor: Decimal


class HourlyRateLimiter:
    def __init__(
        self,
        requests_per_hour: int,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if requests_per_hour < 1:
            raise ValueError("requests_per_hour must be positive")
        self.minimum_interval = 3600 / requests_per_hour
        self.clock = clock
        self.sleeper = sleeper
        self.last_request_at: float | None = None

    def wait(self) -> None:
        now = self.clock()
        if self.last_request_at is not None:
            delay = self.minimum_interval - (now - self.last_request_at)
            if delay > 0:
                self.sleeper(delay)
        self.last_request_at = self.clock()


def _decimal(row: dict[str, Any], key: str, *, default: str | None = None) -> Decimal:
    raw = row.get(key, default)
    if raw is None:
        raise TiingoError(f"Tiingo response is missing {key}")
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError) as exc:
        raise TiingoError(f"Tiingo response has invalid {key}") from exc
    if not value.is_finite():
        raise TiingoError(f"Tiingo response has non-finite {key}")
    return value


def parse_prices(payload: Any) -> list[TiingoPrice]:
    if not isinstance(payload, list):
        raise TiingoError("Tiingo price response must be a list")
    by_date: dict[date, TiingoPrice] = {}
    for raw in payload:
        if not isinstance(raw, dict) or not isinstance(raw.get("date"), str):
            raise TiingoError("Tiingo price row is malformed")
        try:
            price_date = date.fromisoformat(raw["date"][:10])
        except ValueError as exc:
            raise TiingoError("Tiingo price row has invalid date") from exc
        item = TiingoPrice(
            price_date=price_date,
            open=_decimal(raw, "open"),
            high=_decimal(raw, "high"),
            low=_decimal(raw, "low"),
            close=_decimal(raw, "close"),
            volume=_decimal(raw, "volume"),
            adj_open=_decimal(raw, "adjOpen"),
            adj_high=_decimal(raw, "adjHigh"),
            adj_low=_decimal(raw, "adjLow"),
            adj_close=_decimal(raw, "adjClose"),
            adj_volume=_decimal(raw, "adjVolume"),
            dividend_cash=_decimal(raw, "divCash", default="0"),
            split_factor=_decimal(raw, "splitFactor", default="1"),
        )
        prices = (
            item.open,
            item.high,
            item.low,
            item.close,
            item.adj_open,
            item.adj_high,
            item.adj_low,
            item.adj_close,
        )
        if any(value <= 0 for value in prices):
            raise TiingoError(f"Tiingo returned non-positive price for {price_date}")
        if item.volume < 0 or item.adj_volume < 0:
            raise TiingoError(f"Tiingo returned negative volume for {price_date}")
        if item.dividend_cash < 0 or item.split_factor <= 0:
            raise TiingoError(f"Tiingo returned invalid corporate action for {price_date}")
        by_date[price_date] = item
    return [by_date[key] for key in sorted(by_date)]


class TiingoClient:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        limiter: HourlyRateLimiter | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.sleeper = sleeper
        self.limiter = limiter or HourlyRateLimiter(
            self.settings.tiingo_requests_per_hour, sleeper=sleeper
        )
        self.client = httpx.Client(
            base_url=self.settings.tiingo_base_url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Token {self.settings.tiingo_api_token.strip()}",
            },
            timeout=60,
            transport=transport,
        )

    def close(self) -> None:
        self.client.close()

    def prices(self, ticker: str, start_date: date, end_date: date) -> list[TiingoPrice]:
        if not self.settings.tiingo_is_configured:
            raise TiingoNotConfigured("TIINGO_API_TOKEN 尚未設定")
        normalized = ticker.strip().upper().replace(".", "-")
        allowed = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-"
        if not normalized or any(character not in allowed for character in normalized):
            raise TiingoError("invalid Tiingo ticker")
        path = f"/tiingo/daily/{normalized}/prices"
        params = {
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
            "format": "json",
            "resampleFreq": "daily",
        }
        for attempt in range(5):
            self.limiter.wait()
            try:
                response = self.client.get(path, params=params)
            except httpx.HTTPError as exc:
                if attempt == 4:
                    raise TiingoError("Tiingo request failed") from exc
                self.sleeper(2**attempt)
                continue
            if response.status_code == 404:
                raise TiingoSymbolUnavailable(f"Tiingo 無此 ticker：{normalized}")
            if response.status_code in {429, 500, 502, 503, 504}:
                if attempt == 4:
                    raise TiingoError(f"Tiingo request failed with {response.status_code}")
                retry_after = response.headers.get("Retry-After")
                try:
                    delay = float(retry_after) if retry_after else float(2**attempt)
                except ValueError:
                    delay = float(2**attempt)
                self.sleeper(max(0, min(delay, 300)))
                continue
            if response.status_code in {401, 403}:
                raise TiingoNotConfigured("Tiingo token 無效或無 EOD 權限")
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise TiingoError(f"Tiingo request failed with {response.status_code}") from exc
            return parse_prices(response.json())
        raise TiingoError("Tiingo request failed")

    def __enter__(self) -> TiingoClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
