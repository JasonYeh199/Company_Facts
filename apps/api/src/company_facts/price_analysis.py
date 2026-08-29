from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from datetime import date
from decimal import Decimal
from statistics import stdev
from typing import Any

from .models import DailyPrice

TRADING_DAYS = 252
RANK_METRICS = (
    "return_1m",
    "return_3m",
    "return_6m",
    "return_1y",
    "volatility_252d",
    "max_drawdown_1y",
)


def decimal_or_none(value: float | Decimal | None) -> Decimal | None:
    if value is None or not math.isfinite(float(value)):
        return None
    return Decimal(str(value))


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _sample_std(values: Sequence[float]) -> float | None:
    return stdev(values) if len(values) >= 2 else None


def _rolling_mean(values: Sequence[float], index: int, window: int) -> float | None:
    if index + 1 < window:
        return None
    return _mean(values[index - window + 1 : index + 1])


def _ema(values: Sequence[float], period: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    if len(values) < period:
        return result
    seed = sum(values[:period]) / period
    result[period - 1] = seed
    multiplier = 2 / (period + 1)
    current = seed
    for index in range(period, len(values)):
        current = (values[index] - current) * multiplier + current
        result[index] = current
    return result


def _rsi(values: Sequence[float], period: int = 14) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    if len(values) <= period:
        return result
    changes = [values[index] - values[index - 1] for index in range(1, len(values))]
    average_gain = sum(max(change, 0) for change in changes[:period]) / period
    average_loss = sum(max(-change, 0) for change in changes[:period]) / period

    def score(gain: float, loss: float) -> float:
        if loss == 0:
            return 100.0
        return 100 - (100 / (1 + gain / loss))

    result[period] = score(average_gain, average_loss)
    for index in range(period + 1, len(values)):
        change = changes[index - 1]
        average_gain = (average_gain * (period - 1) + max(change, 0)) / period
        average_loss = (average_loss * (period - 1) + max(-change, 0)) / period
        result[index] = score(average_gain, average_loss)
    return result


def build_indicator_rows(prices: Sequence[DailyPrice]) -> list[dict[str, Any]]:
    ordered = sorted(prices, key=lambda item: item.price_date)
    closes = [float(item.adj_close) for item in ordered]
    volumes = [float(item.adj_volume) for item in ordered]
    ema_12 = _ema(closes, 12)
    ema_26 = _ema(closes, 26)
    rsi_14 = _rsi(closes)
    macd_values = [
        (short - long) if short is not None and long is not None else None
        for short, long in zip(ema_12, ema_26, strict=True)
    ]
    compact_macd = [value for value in macd_values if value is not None]
    compact_signal = _ema(compact_macd, 9)
    signal_by_index: list[float | None] = [None] * len(ordered)
    compact_index = 0
    for index, value in enumerate(macd_values):
        if value is not None:
            signal_by_index[index] = compact_signal[compact_index]
            compact_index += 1

    rows: list[dict[str, Any]] = []
    peak = float("-inf")
    for index, price in enumerate(ordered):
        close = closes[index]
        peak = max(peak, close)
        daily_return = close / closes[index - 1] - 1 if index else None
        log_return = math.log(close / closes[index - 1]) if index else None

        bollinger_window = closes[index - 19 : index + 1] if index + 1 >= 20 else []
        bollinger_mid = _mean(bollinger_window)
        bollinger_std = _sample_std(bollinger_window)
        average_volume = _mean(volumes[index - 19 : index + 1]) if index + 1 >= 20 else None
        signal = signal_by_index[index]
        macd = macd_values[index]
        rows.append(
            {
                "instrument_id": price.instrument_id,
                "price_date": price.price_date,
                "daily_return": decimal_or_none(daily_return),
                "log_return": decimal_or_none(log_return),
                "sma_20": decimal_or_none(_rolling_mean(closes, index, 20)),
                "sma_50": decimal_or_none(_rolling_mean(closes, index, 50)),
                "sma_200": decimal_or_none(_rolling_mean(closes, index, 200)),
                "ema_12": decimal_or_none(ema_12[index]),
                "ema_26": decimal_or_none(ema_26[index]),
                "rsi_14": decimal_or_none(rsi_14[index]),
                "macd": decimal_or_none(macd),
                "macd_signal": decimal_or_none(signal),
                "macd_histogram": decimal_or_none(
                    macd - signal if macd is not None and signal is not None else None
                ),
                "bollinger_mid": decimal_or_none(bollinger_mid),
                "bollinger_upper": decimal_or_none(
                    bollinger_mid + 2 * bollinger_std
                    if bollinger_mid is not None and bollinger_std is not None
                    else None
                ),
                "bollinger_lower": decimal_or_none(
                    bollinger_mid - 2 * bollinger_std
                    if bollinger_mid is not None and bollinger_std is not None
                    else None
                ),
                "drawdown": decimal_or_none(close / peak - 1),
                "volume_average_20": decimal_or_none(average_volume),
                "volume_ratio_20": decimal_or_none(
                    volumes[index] / average_volume if average_volume else None
                ),
            }
        )
    return rows


def _subtract_months(value: date, months: int) -> date:
    year, month_index = divmod(value.year * 12 + value.month - 1 - months, 12)
    month = month_index + 1
    day = value.day
    while day > 28:
        try:
            return date(year, month, day)
        except ValueError:
            day -= 1
    return date(year, month, day)


def _price_at_or_before(prices: Sequence[DailyPrice], target: date) -> DailyPrice | None:
    return next((item for item in reversed(prices) if item.price_date <= target), None)


def _return_since(
    prices: Sequence[DailyPrice], target: date, *, annualize: bool = False
) -> Decimal | None:
    if not prices:
        return None
    start = _price_at_or_before(prices, target)
    end = prices[-1]
    if start is None or start.price_date == end.price_date or start.adj_close <= 0:
        return None
    ratio = float(end.adj_close / start.adj_close)
    if annualize:
        years = (end.price_date - start.price_date).days / 365.25
        if years <= 0:
            return None
        return decimal_or_none(ratio ** (1 / years) - 1)
    return decimal_or_none(ratio - 1)


def _maximum_drawdown(prices: Sequence[DailyPrice]) -> Decimal | None:
    if not prices:
        return None
    peak = float("-inf")
    worst = 0.0
    for price in prices:
        value = float(price.adj_close)
        peak = max(peak, value)
        worst = min(worst, value / peak - 1)
    return decimal_or_none(worst)


def _window(prices: Sequence[DailyPrice], start: date) -> list[DailyPrice]:
    return [item for item in prices if item.price_date >= start]


def _percentile(values: Sequence[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def build_analysis_summary(prices: Sequence[DailyPrice]) -> dict[str, Any]:
    ordered = sorted(prices, key=lambda item: item.price_date)
    if not ordered:
        return {}
    latest = ordered[-1]
    as_of = latest.price_date
    returns: dict[str, Decimal | None] = {
        "return_1d": decimal_or_none(
            float(latest.adj_close / ordered[-2].adj_close - 1) if len(ordered) >= 2 else None
        ),
        "return_1w": _return_since(ordered, as_of.fromordinal(as_of.toordinal() - 7)),
        "return_1m": _return_since(ordered, _subtract_months(as_of, 1)),
        "return_3m": _return_since(ordered, _subtract_months(as_of, 3)),
        "return_6m": _return_since(ordered, _subtract_months(as_of, 6)),
        "return_ytd": _return_since(ordered, date(as_of.year - 1, 12, 31)),
        "return_1y": _return_since(ordered, _subtract_months(as_of, 12)),
        "return_3y_annualized": _return_since(
            ordered, _subtract_months(as_of, 36), annualize=True
        ),
        "return_5y_annualized": _return_since(
            ordered, _subtract_months(as_of, 60), annualize=True
        ),
        "return_10y_annualized": _return_since(
            ordered, _subtract_months(as_of, 120), annualize=True
        ),
    }
    daily_returns = [
        float(ordered[index].adj_close / ordered[index - 1].adj_close - 1)
        for index in range(1, len(ordered))
    ]
    log_returns = [math.log1p(value) for value in daily_returns]

    def volatility(window: int) -> Decimal | None:
        values = log_returns[-window:]
        standard_deviation = _sample_std(values) if len(values) >= window else None
        return decimal_or_none(
            standard_deviation * math.sqrt(TRADING_DAYS)
            if standard_deviation is not None
            else None
        )

    trailing_252 = daily_returns[-252:] if len(daily_returns) >= 252 else []
    negative = [min(value, 0) for value in trailing_252]
    downside = (
        math.sqrt(sum(value * value for value in negative) / len(negative))
        * math.sqrt(TRADING_DAYS)
        if negative
        else None
    )
    var_95 = _percentile(trailing_252, 0.05)
    cvar_values = [value for value in trailing_252 if var_95 is not None and value <= var_95]

    one_year = _window(ordered, _subtract_months(as_of, 12))
    three_year = _window(ordered, _subtract_months(as_of, 36))
    ten_year = _window(ordered, _subtract_months(as_of, 120))
    trailing_high = max((float(item.high) for item in one_year), default=None)
    trailing_low = min((float(item.low) for item in one_year), default=None)
    current = float(latest.close)
    all_time_peak = max(float(item.adj_close) for item in ordered)
    risk = {
        "volatility_20d": volatility(20),
        "volatility_60d": volatility(60),
        "volatility_252d": volatility(252),
        "downside_deviation_252d": decimal_or_none(downside),
        "current_drawdown": decimal_or_none(float(latest.adj_close) / all_time_peak - 1),
        "max_drawdown_1y": _maximum_drawdown(one_year),
        "max_drawdown_3y": _maximum_drawdown(three_year),
        "max_drawdown_10y": _maximum_drawdown(ten_year),
        "var_95_1d": decimal_or_none(var_95),
        "cvar_95_1d": decimal_or_none(_mean(cvar_values)),
        "high_52w": decimal_or_none(trailing_high),
        "low_52w": decimal_or_none(trailing_low),
        "distance_from_52w_high": decimal_or_none(
            current / trailing_high - 1 if trailing_high else None
        ),
        "distance_from_52w_low": decimal_or_none(
            current / trailing_low - 1 if trailing_low else None
        ),
        "worst_day_1y": decimal_or_none(min(trailing_252) if trailing_252 else None),
    }
    return {"as_of": as_of, "returns": returns, "risk": risk}


def rank_metric_values(
    values: Iterable[tuple[int, Decimal]], *, lower_is_better: bool = False
) -> list[dict[str, Any]]:
    items = list(values)
    items.sort(key=lambda item: (item[1], item[0]), reverse=not lower_is_better)
    size = len(items)
    result: list[dict[str, Any]] = []
    cursor = 0
    while cursor < size:
        end = cursor + 1
        while end < size and items[end][1] == items[cursor][1]:
            end += 1
        average_rank = (cursor + 1 + end) / 2
        percentile = 1.0 if size == 1 else 1 - (average_rank - 1) / (size - 1)
        for instrument_id, value in items[cursor:end]:
            result.append(
                {
                    "instrument_id": instrument_id,
                    "value": value,
                    "rank": max(1, round(average_rank)),
                    "percentile": Decimal(str(percentile)),
                    "universe_size": size,
                }
            )
        cursor = end
    return result
