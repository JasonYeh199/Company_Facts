from __future__ import annotations

import logging
import math
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from .config import Settings, get_settings
from .db import SessionLocal
from .models import (
    Company,
    DailyPrice,
    DailyPriceIndicator,
    PriceInstrument,
    PriceRank,
    PriceSyncItem,
    Security,
    SyncRun,
)
from .price_analysis import (
    RANK_METRICS,
    build_analysis_summary,
    build_indicator_rows,
    rank_metric_values,
)
from .tiingo_client import TiingoClient, TiingoPrice, TiingoSymbolUnavailable
from .top_companies import TOP100_TICKERS

logger = logging.getLogger(__name__)


def _years_ago(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year - years)
    except ValueError:
        return value.replace(year=value.year - years, day=28)


def ensure_price_instruments(session: Session) -> list[PriceInstrument]:
    securities = list(
        session.scalars(
            select(Security)
            .join(Company)
            .options(selectinload(Security.company))
            .where(
                Company.is_active.is_(True),
                Company.supported.is_(True),
                Security.is_active.is_(True),
                Security.ticker.in_(TOP100_TICKERS),
            )
            .order_by(Company.cik)
        )
    )
    by_ticker: dict[str, list[Security]] = defaultdict(list)
    by_company: dict[int, list[Security]] = defaultdict(list)
    for security in securities:
        by_ticker[security.ticker].append(security)
        by_company[security.company_id].append(security)
    missing = sorted(TOP100_TICKERS - by_ticker.keys())
    duplicate_tickers = sorted(
        ticker for ticker, items in by_ticker.items() if len(items) != 1
    )
    duplicate_companies = sorted(
        company_id for company_id, items in by_company.items() if len(items) != 1
    )
    if missing or duplicate_tickers or duplicate_companies:
        raise RuntimeError(
            "Top 100 研究主 ticker 映射不完整："
            f"missing={missing}, duplicate_tickers={duplicate_tickers}, "
            f"duplicate_companies={duplicate_companies}"
        )

    existing = {
        item.company_id: item
        for item in session.scalars(
            select(PriceInstrument).where(PriceInstrument.is_primary.is_(True))
        )
    }
    for company_id, items in by_company.items():
        security = items[0]
        instrument = existing.get(company_id)
        if instrument is None:
            instrument = PriceInstrument(
                company_id=company_id,
                security_id=security.id,
                provider="tiingo",
                provider_symbol=security.ticker,
                is_primary=True,
                status="pending",
            )
            session.add(instrument)
        else:
            instrument.security_id = security.id
            instrument.provider_symbol = security.ticker
    session.flush()
    return list(
        session.scalars(
            select(PriceInstrument)
            .options(selectinload(PriceInstrument.company), selectinload(PriceInstrument.security))
            .where(
                PriceInstrument.is_primary.is_(True),
                PriceInstrument.provider_symbol.in_(TOP100_TICKERS),
            )
            .order_by(PriceInstrument.provider_symbol)
        )
    )


def _assign_price(target: DailyPrice, source: TiingoPrice, run_id: str) -> None:
    target.open = source.open
    target.high = source.high
    target.low = source.low
    target.close = source.close
    target.volume = source.volume
    target.adj_open = source.adj_open
    target.adj_high = source.adj_high
    target.adj_low = source.adj_low
    target.adj_close = source.adj_close
    target.adj_volume = source.adj_volume
    target.dividend_cash = source.dividend_cash
    target.split_factor = source.split_factor
    target.source_run_id = run_id
    target.fetched_at = datetime.now(UTC)


def upsert_prices(
    session: Session,
    instrument: PriceInstrument,
    prices: list[TiingoPrice],
    run_id: str,
) -> int:
    if not prices:
        return 0
    dates = [item.price_date for item in prices]
    existing = {
        item.price_date: item
        for item in session.scalars(
            select(DailyPrice).where(
                DailyPrice.instrument_id == instrument.id,
                DailyPrice.price_date.in_(dates),
            )
        )
    }
    for item in prices:
        target = existing.get(item.price_date)
        if target is None:
            target = DailyPrice(instrument_id=instrument.id, price_date=item.price_date)
            session.add(target)
        _assign_price(target, item, run_id)
    instrument.coverage_start = min(
        [item.price_date for item in prices]
        + ([instrument.coverage_start] if instrument.coverage_start else [])
    )
    instrument.coverage_end = max(
        [item.price_date for item in prices]
        + ([instrument.coverage_end] if instrument.coverage_end else [])
    )
    instrument.last_synced_at = datetime.now(UTC)
    instrument.status = "available"
    instrument.last_error = None
    session.flush()
    return len(prices)


def rebuild_indicators(session: Session, instrument_id: int) -> int:
    prices = list(
        session.scalars(
            select(DailyPrice)
            .where(DailyPrice.instrument_id == instrument_id)
            .order_by(DailyPrice.price_date)
        )
    )
    session.execute(
        delete(DailyPriceIndicator).where(DailyPriceIndicator.instrument_id == instrument_id)
    )
    rows = build_indicator_rows(prices)
    session.add_all(DailyPriceIndicator(**row) for row in rows)
    return len(rows)


def _sync_one(
    session: Session,
    run_id: str,
    item: PriceSyncItem,
    instrument: PriceInstrument,
    client: TiingoClient,
    settings: Settings,
    *,
    force_full: bool,
) -> int:
    today = date.today()
    full_start = _years_ago(today, settings.tiingo_history_years)
    start = (
        full_start
        if force_full or instrument.coverage_end is None
        else max(full_start, instrument.coverage_end - timedelta(days=settings.tiingo_overlap_days))
    )
    item.status = "running"
    item.requested_from = start
    item.requested_to = today
    item.started_at = datetime.now(UTC)
    item.error = None
    session.commit()

    incoming = client.prices(instrument.provider_symbol, start, today)
    has_new_action = instrument.coverage_end is not None and any(
        row.price_date > instrument.coverage_end
        and (row.dividend_cash != 0 or row.split_factor != 1)
        for row in incoming
    )
    if has_new_action and start > full_start:
        incoming = client.prices(instrument.provider_symbol, full_start, today)
        item.requested_from = full_start
    count = upsert_prices(session, instrument, incoming, run_id)
    rebuild_indicators(session, instrument.id)
    item.status = "completed"
    item.row_count = count
    item.completed_at = datetime.now(UTC)
    session.commit()
    return count


def rebuild_price_ranks(session: Session) -> date | None:
    instruments = list(
        session.scalars(
            select(PriceInstrument).where(
                PriceInstrument.is_primary.is_(True),
                PriceInstrument.provider_symbol.in_(TOP100_TICKERS),
                PriceInstrument.status == "available",
            )
        )
    )
    if not instruments:
        return None
    minimum = max(1, math.ceil(len(instruments) * 0.95))
    as_of = session.scalar(
        select(DailyPrice.price_date)
        .where(DailyPrice.instrument_id.in_([item.id for item in instruments]))
        .group_by(DailyPrice.price_date)
        .having(func.count(DailyPrice.instrument_id) >= minimum)
        .order_by(DailyPrice.price_date.desc())
        .limit(1)
    )
    if as_of is None:
        return None
    values: dict[str, list[tuple[int, Decimal]]] = defaultdict(list)
    for instrument in instruments:
        prices = list(
            session.scalars(
                select(DailyPrice)
                .where(
                    DailyPrice.instrument_id == instrument.id,
                    DailyPrice.price_date <= as_of,
                )
                .order_by(DailyPrice.price_date)
            )
        )
        summary = build_analysis_summary(prices)
        combined = {**summary.get("returns", {}), **summary.get("risk", {})}
        for metric in RANK_METRICS:
            value = combined.get(metric)
            if value is not None:
                values[metric].append((instrument.id, value))
    session.execute(delete(PriceRank).where(PriceRank.as_of == as_of))
    for metric, metric_values in values.items():
        lower_is_better = metric == "volatility_252d"
        for row in rank_metric_values(metric_values, lower_is_better=lower_is_better):
            session.add(PriceRank(as_of=as_of, metric_code=metric, **row))
    session.commit()
    return as_of


def run_price_sync(
    run_id: str,
    settings: Settings | None = None,
    *,
    cik: str | None = None,
    client: TiingoClient | None = None,
    force_full: bool | None = None,
) -> None:
    active_settings = settings or get_settings()
    owns_client = client is None
    active_client = client or TiingoClient(active_settings)
    try:
        with SessionLocal() as session:
            run = session.get(SyncRun, run_id)
            if run is None:
                raise RuntimeError(f"sync run not found: {run_id}")
            instruments = ensure_price_instruments(session)
            if cik:
                instruments = [item for item in instruments if item.company.cik == cik]
            if not instruments:
                raise RuntimeError("找不到可同步的研究 ticker")
            existing_items = {
                item.instrument_id: item
                for item in session.scalars(
                    select(PriceSyncItem).where(PriceSyncItem.run_id == run_id)
                )
            }
            for instrument in instruments:
                if instrument.id not in existing_items:
                    sync_item = PriceSyncItem(
                        run_id=run_id, instrument_id=instrument.id, status="pending"
                    )
                    session.add(sync_item)
                    existing_items[instrument.id] = sync_item
            run.status = "running"
            run.started_at = run.started_at or datetime.now(UTC)
            run.progress_total = len(instruments)
            run.message = "正在同步 Tiingo Daily EOD"
            session.commit()

        failed = 0
        completed = 0
        weekly_full = date.today().weekday() == 6
        for instrument in instruments:
            with SessionLocal() as session:
                sync_item = session.scalar(
                    select(PriceSyncItem).where(
                        PriceSyncItem.run_id == run_id,
                        PriceSyncItem.instrument_id == instrument.id,
                    )
                )
                current_instrument = session.get(PriceInstrument, instrument.id)
                if sync_item is None or current_instrument is None:
                    continue
                if sync_item.status == "completed":
                    completed += 1
                    continue
                try:
                    _sync_one(
                        session,
                        run_id,
                        sync_item,
                        current_instrument,
                        active_client,
                        active_settings,
                        force_full=(
                            force_full
                            if force_full is not None
                            else weekly_full or current_instrument.coverage_end is None
                        ),
                    )
                    completed += 1
                except TiingoSymbolUnavailable as exc:
                    session.rollback()
                    sync_item = session.scalar(
                        select(PriceSyncItem).where(
                            PriceSyncItem.run_id == run_id,
                            PriceSyncItem.instrument_id == instrument.id,
                        )
                    )
                    current_instrument = session.get(PriceInstrument, instrument.id)
                    if sync_item and current_instrument:
                        sync_item.status = "unsupported"
                        sync_item.error = str(exc)
                        sync_item.completed_at = datetime.now(UTC)
                        current_instrument.status = "unsupported"
                        current_instrument.last_error = str(exc)
                        session.commit()
                    failed += 1
                except Exception as exc:
                    logger.exception("Price sync failed for %s", instrument.provider_symbol)
                    session.rollback()
                    sync_item = session.scalar(
                        select(PriceSyncItem).where(
                            PriceSyncItem.run_id == run_id,
                            PriceSyncItem.instrument_id == instrument.id,
                        )
                    )
                    current_instrument = session.get(PriceInstrument, instrument.id)
                    if sync_item:
                        sync_item.status = "failed"
                        sync_item.error = f"{type(exc).__name__}: {exc}"
                        sync_item.completed_at = datetime.now(UTC)
                    if current_instrument:
                        current_instrument.status = "error"
                        current_instrument.last_error = f"{type(exc).__name__}: {exc}"
                    session.commit()
                    failed += 1
                run = session.get(SyncRun, run_id)
                if run:
                    run.progress_current = completed + failed
                    run.message = f"Tiingo EOD：{completed} 成功、{failed} 失敗"
                    session.commit()

        with SessionLocal() as session:
            rank_date = rebuild_price_ranks(session)
            run = session.get(SyncRun, run_id)
            if run:
                run.status = "completed_with_errors" if failed else "completed"
                run.progress_current = completed + failed
                run.completed_at = datetime.now(UTC)
                run.message = (
                    f"Tiingo EOD 完成：{completed} 成功、{failed} 失敗"
                    + (f"；排名日 {rank_date}" if rank_date else "")
                )
                session.commit()
    finally:
        if owns_client:
            active_client.close()
