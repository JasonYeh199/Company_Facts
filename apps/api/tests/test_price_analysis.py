from datetime import date, timedelta
from decimal import Decimal

import pytest

from company_facts.models import DailyPrice
from company_facts.price_analysis import (
    build_analysis_summary,
    build_indicator_rows,
    rank_metric_values,
)


def price_row(index: int, close: Decimal, *, volume: Decimal = Decimal("1000")) -> DailyPrice:
    return DailyPrice(
        instrument_id=1,
        price_date=date(2025, 1, 1) + timedelta(days=index),
        open=close,
        high=close * Decimal("1.01"),
        low=close * Decimal("0.99"),
        close=close,
        volume=volume,
        adj_open=close,
        adj_high=close * Decimal("1.01"),
        adj_low=close * Decimal("0.99"),
        adj_close=close,
        adj_volume=volume,
        dividend_cash=Decimal("0"),
        split_factor=Decimal("1"),
    )


def test_standard_indicators_and_drawdown() -> None:
    prices = [price_row(index, Decimal(100 + index)) for index in range(260)]
    rows = build_indicator_rows(prices)

    assert rows[0]["daily_return"] is None
    assert rows[19]["sma_20"] == Decimal("109.5")
    assert rows[49]["sma_50"] == Decimal("124.5")
    assert rows[199]["sma_200"] == Decimal("199.5")
    assert rows[-1]["rsi_14"] == Decimal("100.0")
    assert rows[-1]["drawdown"] == Decimal("0.0")
    assert rows[-1]["volume_ratio_20"] == Decimal("1.0")
    assert rows[-1]["macd"] is not None
    assert rows[-1]["bollinger_upper"] > rows[-1]["bollinger_mid"]


def test_summary_returns_risk_and_missing_history() -> None:
    prices = [price_row(index, Decimal(100 + index)) for index in range(400)]
    summary = build_analysis_summary(prices)

    assert float(summary["returns"]["return_1d"]) == pytest.approx(0.002008, rel=1e-3)
    assert summary["returns"]["return_1m"] is not None
    assert summary["returns"]["return_3y_annualized"] is None
    assert summary["risk"]["volatility_252d"] is not None
    assert summary["risk"]["max_drawdown_1y"] == Decimal("0.0")
    assert summary["risk"]["distance_from_52w_high"] < 0
    assert summary["risk"]["var_95_1d"] is not None


def test_rank_direction_and_ties() -> None:
    higher = rank_metric_values(
        [(1, Decimal("0.2")), (2, Decimal("0.1")), (3, Decimal("0.1"))]
    )
    by_id = {row["instrument_id"]: row for row in higher}
    assert by_id[1]["rank"] == 1
    assert by_id[1]["percentile"] == Decimal("1.0")
    assert by_id[2]["rank"] == by_id[3]["rank"] == 2

    lower = rank_metric_values(
        [(1, Decimal("0.3")), (2, Decimal("0.1"))], lower_is_better=True
    )
    assert {row["instrument_id"]: row["rank"] for row in lower} == {2: 1, 1: 2}


def test_indicator_handles_drawdown_and_zero_volume() -> None:
    prices = [price_row(0, Decimal("100")), price_row(1, Decimal("80"))]
    rows = build_indicator_rows(prices)
    assert rows[-1]["drawdown"] == Decimal("-0.19999999999999996")
    assert rows[-1]["volume_average_20"] is None
