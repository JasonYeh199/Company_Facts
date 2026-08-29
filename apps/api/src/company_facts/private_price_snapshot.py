from __future__ import annotations

import gzip
import json
import re
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session, selectinload

from .models import (
    Company,
    DailyPrice,
    DailyPriceIndicator,
    Filing,
    PriceInstrument,
    PriceRank,
    SyncRun,
)
from .price_analysis import build_analysis_summary

ACCESSION_PATTERN = re.compile(r"^\d{10}-\d{2}-\d{6}$")
INDICATOR_FIELDS = (
    "daily_return",
    "log_return",
    "sma_20",
    "sma_50",
    "sma_200",
    "ema_12",
    "ema_26",
    "rsi_14",
    "macd",
    "macd_signal",
    "macd_histogram",
    "bollinger_mid",
    "bollinger_upper",
    "bollinger_lower",
    "drawdown",
    "volume_average_20",
    "volume_ratio_20",
)
TECHNICAL_FIELDS = (
    "sma_20",
    "sma_50",
    "sma_200",
    "rsi_14",
    "macd",
    "macd_signal",
    "macd_histogram",
    "bollinger_mid",
    "bollinger_upper",
    "bollinger_lower",
    "volume_average_20",
    "volume_ratio_20",
)


def _iso(value: date | datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z")


def _decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    rendered = format(value, "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return _decimal(value)
    if isinstance(value, (date, datetime)):
        return _iso(value)
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _sec_url(cik: str, accession: str | None) -> str | None:
    if not accession or ACCESSION_PATTERN.fullmatch(accession) is None:
        return None
    return (
        f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
        f"{accession.replace('-', '')}/{accession}-index.html"
    )


def _company_payload(company: Company) -> dict[str, Any]:
    return {
        "cik": company.cik,
        "name": company.name,
        "supported": company.supported,
        "accounting_standard": company.accounting_standard,
        "tickers": [
            {
                "ticker": security.ticker,
                "exchange": security.exchange,
                "is_active": security.is_active,
            }
            for security in sorted(
                (item for item in company.securities if item.is_active),
                key=lambda item: item.ticker,
            )
        ],
    }


def _write_json(path: Path, payload: Any) -> int:
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    compressed = gzip.compress(encoded, compresslevel=9, mtime=0)
    target = path.with_suffix(f"{path.suffix}.gz")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(compressed)
    return len(compressed)


def _years_ago(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year - years)
    except ValueError:
        return value.replace(year=value.year - years, day=28)


def _sync_payload(run: SyncRun | None) -> dict[str, Any] | None:
    if run is None:
        return None
    return {
        "id": run.id,
        "kind": run.kind,
        "cik": run.cik,
        "status": run.status,
        "progress_current": run.progress_current,
        "progress_total": run.progress_total,
        "message": f"{run.message or 'Tiingo 同步'} · 私人快照",
        "error": run.error,
        "source_etag": run.source_etag,
        "created_at": _iso(run.created_at),
        "started_at": _iso(run.started_at),
        "completed_at": _iso(run.completed_at),
        "price_items": [],
    }


def _filing_reactions(
    company: Company,
    prices: list[DailyPrice],
    filings: list[Filing],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for filing in filings:
        before = next((item for item in reversed(prices) if item.price_date < filing.filed), None)
        after = [item for item in prices if item.price_date >= filing.filed]

        output.append(
            {
                "filed": _iso(filing.filed),
                "form": filing.form,
                "accession": filing.accession,
                "url": _sec_url(company.cik, filing.accession),
                "return_1d": _reaction(before, after, 0),
                "return_5d": _reaction(before, after, 4),
                "return_20d": _reaction(before, after, 19),
            }
        )
    return output


def _reaction(
    before: DailyPrice | None,
    after: list[DailyPrice],
    index: int,
) -> str | None:
    if before is None or len(after) <= index:
        return None
    return _decimal(after[index].adj_close / before.adj_close - 1)


def _rankings(
    session: Session,
    instrument: PriceInstrument,
    latest_date: date,
) -> list[dict[str, Any]]:
    rank_date = session.scalar(
        select(func.max(PriceRank.as_of)).where(
            PriceRank.instrument_id == instrument.id,
            PriceRank.as_of <= latest_date,
        )
    )
    if rank_date is None:
        return []
    output: list[dict[str, Any]] = []
    ranks = session.scalars(
        select(PriceRank)
        .where(PriceRank.instrument_id == instrument.id, PriceRank.as_of == rank_date)
        .order_by(PriceRank.metric_code)
    )
    for rank in ranks:
        peers = session.execute(
            select(PriceRank, PriceInstrument, Company)
            .join(PriceInstrument, PriceInstrument.id == PriceRank.instrument_id)
            .join(Company, Company.id == PriceInstrument.company_id)
            .where(
                PriceRank.as_of == rank.as_of,
                PriceRank.metric_code == rank.metric_code,
                PriceRank.rank >= max(1, rank.rank - 2),
                PriceRank.rank <= rank.rank + 2,
            )
            .order_by(PriceRank.rank, PriceInstrument.provider_symbol)
        ).all()
        output.append(
            {
                "metric": rank.metric_code,
                "value": _decimal(rank.value),
                "rank": rank.rank,
                "percentile": _decimal(rank.percentile),
                "universe_size": rank.universe_size,
                "as_of": _iso(rank.as_of),
                "neighbors": [
                    {
                        "ticker": peer_instrument.provider_symbol,
                        "company_name": peer_company.name,
                        "rank": peer_rank.rank,
                        "value": _decimal(peer_rank.value),
                    }
                    for peer_rank, peer_instrument, peer_company in peers
                ],
            }
        )
    return output


def _instrument_payload(
    session: Session,
    instrument: PriceInstrument,
    company_payload: dict[str, Any],
) -> tuple[dict[str, Any] | None, int]:
    price_rows = list(
        session.execute(
            select(DailyPrice, DailyPriceIndicator)
            .outerjoin(
                DailyPriceIndicator,
                and_(
                    DailyPriceIndicator.instrument_id == DailyPrice.instrument_id,
                    DailyPriceIndicator.price_date == DailyPrice.price_date,
                ),
            )
            .where(DailyPrice.instrument_id == instrument.id)
            .order_by(DailyPrice.price_date)
        )
    )
    prices = [price for price, _indicator in price_rows]
    if not prices:
        return None, 0
    company = instrument.company
    latest = prices[-1]
    floor = _years_ago(latest.price_date, 10)
    filings = list(
        session.scalars(
            select(Filing)
            .where(
                Filing.company_id == company.id,
                Filing.form.in_(("10-K", "10-K/A", "10-Q", "10-Q/A")),
                Filing.filed >= floor,
                Filing.filed <= latest.price_date,
            )
            .order_by(Filing.filed)
        )
    )
    points = []
    events: list[dict[str, Any]] = []
    for price, indicator in price_rows:
        points.append(
            {
                "date": _iso(price.price_date),
                "open": _decimal(price.open),
                "high": _decimal(price.high),
                "low": _decimal(price.low),
                "close": _decimal(price.close),
                "volume": _decimal(price.volume),
                "adj_open": _decimal(price.adj_open),
                "adj_high": _decimal(price.adj_high),
                "adj_low": _decimal(price.adj_low),
                "adj_close": _decimal(price.adj_close),
                "adj_volume": _decimal(price.adj_volume),
                "dividend_cash": _decimal(price.dividend_cash),
                "split_factor": _decimal(price.split_factor),
                "indicators": {
                    field: _decimal(getattr(indicator, field)) if indicator else None
                    for field in INDICATOR_FIELDS
                },
            }
        )
        if price.dividend_cash != 0:
            events.append(
                {
                    "date": _iso(price.price_date),
                    "type": "dividend",
                    "label": "現金股利",
                    "value": _decimal(price.dividend_cash),
                    "accession": None,
                    "url": None,
                }
            )
        if price.split_factor != 1:
            events.append(
                {
                    "date": _iso(price.price_date),
                    "type": "split",
                    "label": "拆併股",
                    "value": _decimal(price.split_factor),
                    "accession": None,
                    "url": None,
                }
            )
    events.extend(
        {
            "date": _iso(filing.filed),
            "type": "filing",
            "label": filing.form,
            "value": None,
            "accession": filing.accession,
            "url": _sec_url(company.cik, filing.accession),
        }
        for filing in filings
    )
    events.sort(key=lambda item: (item["date"], item["type"]))

    summary = build_analysis_summary(prices)
    latest_indicator = price_rows[-1][1]
    coverage = {
        "ticker": instrument.provider_symbol,
        "status": "available",
        "start_date": _iso(prices[0].price_date),
        "end_date": _iso(latest.price_date),
        "last_synced_at": _iso(instrument.last_synced_at),
        "reason": None,
    }
    analysis = {
        "company": company_payload,
        "ticker": instrument.provider_symbol,
        "as_of": _iso(latest.price_date),
        "latest": {
            "date": _iso(latest.price_date),
            "close": _decimal(latest.close),
            "adj_close": _decimal(latest.adj_close),
            "volume": _decimal(latest.volume),
            "change_1d": _decimal(summary["returns"].get("return_1d")),
        },
        "returns": _jsonable(summary["returns"]),
        "risk": _jsonable(summary["risk"]),
        "technical": {
            field: _decimal(getattr(latest_indicator, field)) if latest_indicator else None
            for field in TECHNICAL_FIELDS
        },
        "rankings": _rankings(session, instrument, latest.price_date),
        "filing_reactions": _filing_reactions(company, prices, list(reversed(filings[-20:]))),
    }
    return (
        {
            "coverage": coverage,
            "series": {
                "company": company_payload,
                "ticker": instrument.provider_symbol,
                "currency": instrument.currency,
                "start_date": _iso(prices[0].price_date),
                "end_date": _iso(latest.price_date),
                "points": points,
                "events": events,
            },
            "analysis": analysis,
        },
        len(points),
    )


def export_private_price_snapshots(
    session: Session,
    output_dir: Path,
) -> dict[str, Any]:
    generated_at = datetime.now(UTC)
    latest_run = session.scalar(
        select(SyncRun)
        .where(SyncRun.kind == "prices")
        .order_by(SyncRun.created_at.desc())
        .limit(1)
    )
    instruments = list(
        session.scalars(
            select(PriceInstrument)
            .options(
                selectinload(PriceInstrument.company).selectinload(Company.securities)
            )
            .where(
                PriceInstrument.is_primary.is_(True),
                PriceInstrument.status == "available",
            )
            .order_by(PriceInstrument.provider_symbol)
        )
    )
    total_bytes = 0
    total_points = 0
    latest_date: date | None = None
    exported = 0
    for instrument in instruments:
        company_payload = _company_payload(instrument.company)
        payload, point_count = _instrument_payload(session, instrument, company_payload)
        if payload is None:
            continue
        total_bytes += _write_json(
            output_dir / "private-prices" / f"{instrument.company.cik}.json",
            payload,
        )
        total_points += point_count
        if instrument.coverage_end is not None:
            latest_date = max(latest_date or instrument.coverage_end, instrument.coverage_end)
        exported += 1
    metadata = {
        "included": True,
        "generated_at": _iso(generated_at),
        "company_count": exported,
        "point_count": total_points,
        "latest_date": _iso(latest_date),
        "latest_sync": _sync_payload(latest_run),
    }
    total_bytes += _write_json(output_dir / "private-prices" / "index.json", metadata)
    return {**metadata, "bytes": total_bytes}
