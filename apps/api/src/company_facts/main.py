from __future__ import annotations

import shutil
import uuid
from collections import Counter, defaultdict
from collections.abc import Iterable
from contextlib import asynccontextmanager
from datetime import date, timedelta
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from .config import get_settings
from .db import get_db
from .metrics import METRICS_BY_CODE
from .models import (
    CanonicalValue,
    Company,
    Concept,
    DailyPrice,
    DailyPriceIndicator,
    Fact,
    Filing,
    MetricDefinition,
    PriceInstrument,
    PriceRank,
    PriceSyncItem,
    Security,
    SyncRun,
)
from .price_analysis import build_analysis_summary
from .schemas import (
    CompanyDetail,
    CompanySummary,
    CompareOut,
    FactOut,
    FactsPage,
    FilingReactionOut,
    LatestPriceOut,
    MetricPointOut,
    MetricSeriesOut,
    PriceAnalysisOut,
    PriceCoverageOut,
    PriceEventOut,
    PriceIndicatorOut,
    PricePointOut,
    PriceRankOut,
    PriceRankPeerOut,
    PriceSeriesOut,
    SecurityOut,
    SetupStatus,
    SourceOut,
    StatementOut,
    SyncRunCreate,
    SyncRunOut,
)
from .top_companies import TOP100_TICKERS

settings = get_settings()
DbSession = Annotated[Session, Depends(get_db)]


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield


app = FastAPI(
    title="Company Facts Research API",
    version="0.1.0",
    description="SEC EDGAR Company Facts ingestion and fundamental research API.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


def normalize_cik(value: str) -> str:
    digits = "".join(character for character in value if character.isdigit())
    if not digits or len(digits) > 10:
        raise HTTPException(status_code=404, detail="找不到公司")
    return digits.zfill(10)


def company_summary(company: Company) -> CompanySummary:
    return CompanySummary(
        cik=company.cik,
        name=company.name,
        supported=company.supported,
        accounting_standard=company.accounting_standard,
        tickers=[SecurityOut.model_validate(item) for item in company.securities if item.is_active],
    )


def get_company_or_404(session: Session, cik: str) -> Company:
    company = session.scalar(
        select(Company)
        .options(selectinload(Company.securities))
        .where(Company.cik == normalize_cik(cik))
    )
    if company is None:
        raise HTTPException(status_code=404, detail="找不到公司")
    return company


def sec_filing_url(cik: str, accession: str | None) -> str | None:
    if not accession:
        return None
    return (
        f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
        f"{accession.replace('-', '')}/{accession}-index.html"
    )


def decimal_string(value: Any) -> str:
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered


def optional_decimal(value: Any | None) -> str | None:
    return decimal_string(value) if value is not None else None


def primary_price_instrument(session: Session, company_id: int) -> PriceInstrument | None:
    return session.scalar(
        select(PriceInstrument).where(
            PriceInstrument.company_id == company_id,
            PriceInstrument.is_primary.is_(True),
        )
    )


def price_coverage(session: Session, company: Company) -> PriceCoverageOut:
    instrument = primary_price_instrument(session, company.id)
    if instrument:
        return PriceCoverageOut(
            ticker=instrument.provider_symbol,
            status=instrument.status,
            start_date=instrument.coverage_start,
            end_date=instrument.coverage_end,
            last_synced_at=instrument.last_synced_at,
            reason=instrument.last_error,
        )
    research_ticker = next(
        (
            security.ticker
            for security in company.securities
            if security.is_active and security.ticker in TOP100_TICKERS
        ),
        None,
    )
    return PriceCoverageOut(
        ticker=research_ticker,
        status="pending" if settings.tiingo_is_configured else "unconfigured",
        start_date=None,
        end_date=None,
        last_synced_at=None,
        reason=None if settings.tiingo_is_configured else "TIINGO_API_TOKEN 尚未設定",
    )


def require_price_instrument(session: Session, company: Company) -> PriceInstrument:
    if not settings.tiingo_is_configured:
        raise HTTPException(
            status_code=503,
            detail={"code": "tiingo_not_configured", "message": "TIINGO_API_TOKEN 尚未設定"},
        )
    instrument = primary_price_instrument(session, company.id)
    if instrument is None or instrument.status != "available":
        raise HTTPException(
            status_code=503,
            detail={"code": "price_data_unavailable", "message": "尚未完成此公司的股價同步"},
        )
    return instrument


def latest_values(values: Iterable[CanonicalValue]) -> tuple[list[CanonicalValue], Counter]:
    grouped: dict[tuple[str, str, date, str], list[CanonicalValue]] = defaultdict(list)
    for value in values:
        grouped[(value.metric_code, value.frequency, value.period_end, value.unit)].append(value)
    latest: list[CanonicalValue] = []
    revisions: Counter = Counter()
    for key, group in grouped.items():
        eligible = [value for value in group if value.quality != "ambiguous"]
        if not eligible:
            continue
        eligible.sort(key=lambda value: (value.filed or date.min, value.accession or ""))
        latest.append(eligible[-1])
        revisions[key] = len(group)
    latest.sort(key=lambda value: (value.metric_code, value.period_end))
    return latest, revisions


def point_out(
    value: CanonicalValue, definition: MetricDefinition, cik: str, revision_count: int = 1
) -> MetricPointOut:
    return MetricPointOut(
        metric=value.metric_code,
        name_en=definition.name_en,
        name_zh=definition.name_zh,
        statement=definition.statement,
        frequency=value.frequency,
        period_start=value.period_start,
        period_end=value.period_end,
        fiscal_year=value.fiscal_year,
        fiscal_period=value.fiscal_period,
        value=decimal_string(value.value),
        unit=value.unit,
        is_derived=value.is_derived,
        quality=value.quality,
        revision_count=revision_count,
        source=SourceOut(
            accession=value.accession,
            form=value.form,
            filed=value.filed,
            url=sec_filing_url(cik, value.accession),
            lineage=value.lineage or [],
        ),
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/setup", response_model=SetupStatus)
def setup_status(session: DbSession) -> SetupStatus:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(settings.data_dir).free / 1024**3
    try:
        company_count = session.scalar(select(func.count(Company.id))) or 0
        supported_count = (
            session.scalar(
                select(func.count(Company.id)).where(
                    Company.supported.is_(True), Company.is_active.is_(True)
                )
            )
            or 0
        )
        latest = session.scalar(select(SyncRun).order_by(SyncRun.created_at.desc()).limit(1))
        price_company_count = (
            session.scalar(
                select(func.count(PriceInstrument.id)).where(PriceInstrument.status == "available")
            )
            or 0
        )
        latest_price_date = session.scalar(select(func.max(DailyPrice.price_date)))
        latest_price_sync = session.scalar(
            select(SyncRun)
            .where(SyncRun.kind.in_(("prices", "price_company")))
            .order_by(SyncRun.created_at.desc())
            .limit(1)
        )
        database_connected = True
    except SQLAlchemyError:
        session.rollback()
        company_count = 0
        supported_count = 0
        latest = None
        price_company_count = 0
        latest_price_date = None
        latest_price_sync = None
        database_connected = False
    return SetupStatus(
        sec_configured=settings.sec_is_configured,
        database_connected=database_connected,
        data_dir=str(settings.data_dir),
        free_gib=round(free, 1),
        company_count=company_count,
        supported_company_count=supported_count,
        latest_sync=SyncRunOut.model_validate(latest) if latest else None,
        tiingo_configured=settings.tiingo_is_configured,
        price_company_count=price_company_count,
        latest_price_date=latest_price_date,
        latest_price_sync=(
            SyncRunOut.model_validate(latest_price_sync) if latest_price_sync else None
        ),
    )


@app.get("/api/v1/companies/search", response_model=list[CompanySummary])
def search_companies(
    session: DbSession,
    q: Annotated[str, Query(min_length=1, max_length=100)],
    limit: Annotated[int, Query(ge=1, le=50)] = 12,
) -> list[CompanySummary]:
    term = q.strip()
    cik_term = "".join(character for character in term if character.isdigit())
    conditions = [Company.name.ilike(f"%{term}%"), Security.ticker.ilike(f"%{term}%")]
    if cik_term:
        conditions.append(Company.cik == cik_term.zfill(10))
    companies = session.scalars(
        select(Company)
        .join(Security, isouter=True)
        .options(selectinload(Company.securities))
        .where(Company.is_active.is_(True), or_(*conditions))
        .distinct()
        .limit(limit * 2)
    ).all()
    term_upper = term.upper()
    ranked = sorted(
        companies,
        key=lambda company: (
            0 if any(item.ticker == term_upper for item in company.securities) else 1,
            0 if company.name.lower().startswith(term.lower()) else 1,
            company.name,
        ),
    )[:limit]
    return [company_summary(company) for company in ranked]


@app.get("/api/v1/companies/{cik}", response_model=CompanyDetail)
def company_detail(cik: str, session: DbSession) -> CompanyDetail:
    company = get_company_or_404(session, cik)
    reason = None if company.supported else "首版僅支援具有 US-GAAP Company Facts 的公司"
    return CompanyDetail(
        **company_summary(company).model_dump(),
        sic=company.sic,
        fiscal_year_end=company.fiscal_year_end,
        is_active=company.is_active,
        last_synced_at=company.last_synced_at,
        coverage_reason=reason,
        price_coverage=price_coverage(session, company),
    )


def query_metric_values(
    session: Session,
    company_id: int,
    frequency: str,
    metrics: list[str] | None,
    date_from: date | None,
    date_to: date | None,
) -> list[CanonicalValue]:
    query = select(CanonicalValue).where(
        CanonicalValue.company_id == company_id,
        CanonicalValue.frequency == frequency,
    )
    if metrics:
        query = query.where(CanonicalValue.metric_code.in_(metrics))
    if date_from:
        query = query.where(CanonicalValue.period_end >= date_from)
    if date_to:
        query = query.where(CanonicalValue.period_end <= date_to)
    return list(session.scalars(query))


@app.get("/api/v1/companies/{cik}/metrics", response_model=MetricSeriesOut)
def company_metrics(
    cik: str,
    session: DbSession,
    frequency: Annotated[str, Query(pattern="^(annual|quarterly|ttm)$")] = "annual",
    metric: Annotated[list[str] | None, Query()] = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> MetricSeriesOut:
    company = get_company_or_404(session, cik)
    requested = metric or list(METRICS_BY_CODE)
    invalid = [code for code in requested if code not in METRICS_BY_CODE]
    if invalid:
        raise HTTPException(status_code=422, detail=f"未知指標：{', '.join(invalid)}")
    definitions = {
        item.code: item
        for item in session.scalars(
            select(MetricDefinition).where(MetricDefinition.code.in_(requested))
        )
    }
    values = query_metric_values(session, company.id, frequency, requested, date_from, date_to)
    latest, revisions = latest_values(values)
    result: dict[str, list[MetricPointOut]] = defaultdict(list)
    for value in latest:
        key = (value.metric_code, value.frequency, value.period_end, value.unit)
        result[value.metric_code].append(
            point_out(value, definitions[value.metric_code], company.cik, revisions[key])
        )
    return MetricSeriesOut(
        company=company_summary(company),
        frequency=frequency,
        metrics=dict(result),
        unavailable=[code for code in requested if not result.get(code)],
    )


@app.get("/api/v1/companies/{cik}/statements/{statement}", response_model=StatementOut)
def company_statement(
    cik: str,
    statement: str,
    session: DbSession,
    frequency: Annotated[str, Query(pattern="^(annual|quarterly|ttm)$")] = "annual",
) -> StatementOut:
    if statement not in {"income", "balance", "cash_flow", "ratios"}:
        raise HTTPException(status_code=404, detail="未知財務報表")
    company = get_company_or_404(session, cik)
    definitions = list(
        session.scalars(
            select(MetricDefinition)
            .where(MetricDefinition.statement == statement)
            .order_by(MetricDefinition.code)
        )
    )
    codes = [item.code for item in definitions]
    values, revisions = latest_values(
        query_metric_values(session, company.id, frequency, codes, None, None)
    )
    by_metric: dict[str, list[CanonicalValue]] = defaultdict(list)
    for value in values:
        by_metric[value.metric_code].append(value)
    output: list[dict[str, Any]] = []
    for definition in definitions:
        output.append(
            {
                "code": definition.code,
                "name_en": definition.name_en,
                "name_zh": definition.name_zh,
                "points": [
                    point_out(
                        value,
                        definition,
                        company.cik,
                        revisions[
                            (value.metric_code, value.frequency, value.period_end, value.unit)
                        ],
                    ).model_dump()
                    for value in by_metric.get(definition.code, [])
                ],
            }
        )
    return StatementOut(
        company=company_summary(company),
        statement=statement,
        frequency=frequency,
        metrics=output,
    )


@app.get("/api/v1/companies/{cik}/facts", response_model=FactsPage)
def company_facts(
    cik: str,
    session: DbSession,
    concept: str | None = None,
    form: str | None = None,
    unit: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> FactsPage:
    company = get_company_or_404(session, cik)
    conditions = [Fact.company_id == company.id, Fact.is_active.is_(True)]
    if concept:
        conditions.append(Concept.name.ilike(f"%{concept}%"))
    if form:
        conditions.append(Fact.form == form)
    if unit:
        conditions.append(Fact.unit == unit)
    if date_from:
        conditions.append(Fact.period_end >= date_from)
    if date_to:
        conditions.append(Fact.period_end <= date_to)
    total = (
        session.scalar(select(func.count(Fact.fingerprint)).join(Concept).where(*conditions)) or 0
    )
    rows = session.execute(
        select(Fact, Concept)
        .join(Concept)
        .where(*conditions)
        .order_by(Fact.period_end.desc(), Fact.filed.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return FactsPage(
        items=[
            FactOut(
                id=fact.fingerprint,
                taxonomy=taxonomy.taxonomy,
                concept=taxonomy.name,
                label=taxonomy.label,
                unit=fact.unit,
                period_start=fact.period_start,
                period_end=fact.period_end,
                value=decimal_string(fact.value),
                accession=fact.accession,
                form=fact.form,
                filed=fact.filed,
                fiscal_year=fact.fiscal_year,
                fiscal_period=fact.fiscal_period,
                frame=fact.frame,
                source_url=sec_filing_url(company.cik, fact.accession) or "",
            )
            for fact, taxonomy in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@app.get(
    "/api/v1/companies/{cik}/metrics/{metric}/revisions",
    response_model=list[MetricPointOut],
)
def metric_revisions(
    cik: str,
    metric: str,
    session: DbSession,
    period_end: date,
    frequency: Annotated[str, Query(pattern="^(annual|quarterly|ttm)$")] = "annual",
) -> list[MetricPointOut]:
    company = get_company_or_404(session, cik)
    definition = session.get(MetricDefinition, metric)
    if definition is None:
        raise HTTPException(status_code=404, detail="未知指標")
    values = list(
        session.scalars(
            select(CanonicalValue)
            .where(
                CanonicalValue.company_id == company.id,
                CanonicalValue.metric_code == metric,
                CanonicalValue.frequency == frequency,
                CanonicalValue.period_end == period_end,
            )
            .order_by(CanonicalValue.filed.desc().nullslast(), CanonicalValue.accession.desc())
        )
    )
    return [point_out(value, definition, company.cik, len(values)) for value in values]


def _ten_year_floor(value: date) -> date:
    try:
        return value.replace(year=value.year - 10)
    except ValueError:
        return value.replace(year=value.year - 10, day=28)


def _indicator_out(indicator: DailyPriceIndicator | None) -> PriceIndicatorOut:
    if indicator is None:
        return PriceIndicatorOut()
    fields = (
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
    return PriceIndicatorOut(
        **{field: optional_decimal(getattr(indicator, field)) for field in fields}
    )


@app.get("/api/v1/companies/{cik}/prices", response_model=PriceSeriesOut)
def company_prices(
    cik: str,
    session: DbSession,
    start_date: date | None = None,
    end_date: date | None = None,
) -> PriceSeriesOut:
    company = get_company_or_404(session, cik)
    instrument = require_price_instrument(session, company)
    effective_end = min(end_date or instrument.coverage_end or date.today(), date.today())
    floor = _ten_year_floor(effective_end)
    effective_start = start_date or max(
        instrument.coverage_start or floor, effective_end - timedelta(days=365)
    )
    if effective_start < floor:
        raise HTTPException(status_code=422, detail="股價查詢最多最近十年")
    if effective_start > effective_end:
        raise HTTPException(status_code=422, detail="start_date 不得晚於 end_date")
    rows = session.execute(
        select(DailyPrice, DailyPriceIndicator)
        .outerjoin(
            DailyPriceIndicator,
            and_(
                DailyPriceIndicator.instrument_id == DailyPrice.instrument_id,
                DailyPriceIndicator.price_date == DailyPrice.price_date,
            ),
        )
        .where(
            DailyPrice.instrument_id == instrument.id,
            DailyPrice.price_date >= effective_start,
            DailyPrice.price_date <= effective_end,
        )
        .order_by(DailyPrice.price_date)
    ).all()
    points = [
        PricePointOut(
            date=price.price_date,
            open=decimal_string(price.open),
            high=decimal_string(price.high),
            low=decimal_string(price.low),
            close=decimal_string(price.close),
            volume=decimal_string(price.volume),
            adj_open=decimal_string(price.adj_open),
            adj_high=decimal_string(price.adj_high),
            adj_low=decimal_string(price.adj_low),
            adj_close=decimal_string(price.adj_close),
            adj_volume=decimal_string(price.adj_volume),
            dividend_cash=decimal_string(price.dividend_cash),
            split_factor=decimal_string(price.split_factor),
            indicators=_indicator_out(indicator),
        )
        for price, indicator in rows
    ]
    events: list[PriceEventOut] = []
    for price, _ in rows:
        if price.dividend_cash != 0:
            events.append(
                PriceEventOut(
                    date=price.price_date,
                    type="dividend",
                    label="現金股利",
                    value=decimal_string(price.dividend_cash),
                )
            )
        if price.split_factor != 1:
            events.append(
                PriceEventOut(
                    date=price.price_date,
                    type="split",
                    label="拆併股",
                    value=decimal_string(price.split_factor),
                )
            )
    filings = list(
        session.scalars(
            select(Filing)
            .where(
                Filing.company_id == company.id,
                Filing.form.in_(("10-K", "10-K/A", "10-Q", "10-Q/A")),
                Filing.filed >= effective_start,
                Filing.filed <= effective_end,
            )
            .order_by(Filing.filed)
        )
    )
    events.extend(
        PriceEventOut(
            date=filing.filed,
            type="filing",
            label=filing.form,
            accession=filing.accession,
            url=sec_filing_url(company.cik, filing.accession),
        )
        for filing in filings
    )
    events.sort(key=lambda item: (item.date, item.type))
    return PriceSeriesOut(
        company=company_summary(company),
        ticker=instrument.provider_symbol,
        currency=instrument.currency,
        start_date=effective_start,
        end_date=effective_end,
        points=points,
        events=events,
    )


def _filing_reactions(
    company: Company, prices: list[DailyPrice], filings: list[Filing]
) -> list[FilingReactionOut]:
    output: list[FilingReactionOut] = []
    for filing in filings:
        before = next(
            (price for price in reversed(prices) if price.price_date < filing.filed), None
        )
        after = [price for price in prices if price.price_date >= filing.filed]

        reactions: dict[int, str | None] = {}
        for index in (0, 4, 19):
            reactions[index] = (
                decimal_string(after[index].adj_close / before.adj_close - 1)
                if before is not None and len(after) > index
                else None
            )

        output.append(
            FilingReactionOut(
                filed=filing.filed,
                form=filing.form,
                accession=filing.accession,
                url=sec_filing_url(company.cik, filing.accession),
                return_1d=reactions[0],
                return_5d=reactions[4],
                return_20d=reactions[19],
            )
        )
    return output


@app.get("/api/v1/companies/{cik}/price-analysis", response_model=PriceAnalysisOut)
def company_price_analysis(
    cik: str,
    session: DbSession,
    as_of: date | None = None,
) -> PriceAnalysisOut:
    company = get_company_or_404(session, cik)
    instrument = require_price_instrument(session, company)
    effective_as_of = min(as_of or instrument.coverage_end or date.today(), date.today())
    prices = list(
        session.scalars(
            select(DailyPrice)
            .where(
                DailyPrice.instrument_id == instrument.id,
                DailyPrice.price_date >= _ten_year_floor(effective_as_of),
                DailyPrice.price_date <= effective_as_of,
            )
            .order_by(DailyPrice.price_date)
        )
    )
    if not prices:
        raise HTTPException(status_code=503, detail="所選日期沒有價格資料")
    summary = build_analysis_summary(prices)
    latest_price = prices[-1]
    latest_indicator = session.get(
        DailyPriceIndicator, (instrument.id, latest_price.price_date)
    )
    technical_fields = (
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
    technical = {
        field: optional_decimal(getattr(latest_indicator, field)) if latest_indicator else None
        for field in technical_fields
    }
    rank_as_of = session.scalar(
        select(func.max(PriceRank.as_of)).where(
            PriceRank.instrument_id == instrument.id,
            PriceRank.as_of <= latest_price.price_date,
        )
    )
    rankings: list[PriceRankOut] = []
    if rank_as_of:
        current_ranks = list(
            session.scalars(
                select(PriceRank)
                .where(
                    PriceRank.instrument_id == instrument.id,
                    PriceRank.as_of == rank_as_of,
                )
                .order_by(PriceRank.metric_code)
            )
        )
        for rank in current_ranks:
            neighbor_rows = session.execute(
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
            rankings.append(
                PriceRankOut(
                    metric=rank.metric_code,
                    value=decimal_string(rank.value),
                    rank=rank.rank,
                    percentile=decimal_string(rank.percentile),
                    universe_size=rank.universe_size,
                    as_of=rank.as_of,
                    neighbors=[
                        PriceRankPeerOut(
                            ticker=peer_instrument.provider_symbol,
                            company_name=peer_company.name,
                            rank=peer_rank.rank,
                            value=decimal_string(peer_rank.value),
                        )
                        for peer_rank, peer_instrument, peer_company in neighbor_rows
                    ],
                )
            )
    filings = list(
        session.scalars(
            select(Filing)
            .where(
                Filing.company_id == company.id,
                Filing.form.in_(("10-K", "10-K/A", "10-Q", "10-Q/A")),
                Filing.filed <= latest_price.price_date,
                Filing.filed >= _ten_year_floor(latest_price.price_date),
            )
            .order_by(Filing.filed.desc())
            .limit(20)
        )
    )
    change_1d = summary["returns"].get("return_1d")
    return PriceAnalysisOut(
        company=company_summary(company),
        ticker=instrument.provider_symbol,
        as_of=latest_price.price_date,
        latest=LatestPriceOut(
            date=latest_price.price_date,
            close=decimal_string(latest_price.close),
            adj_close=decimal_string(latest_price.adj_close),
            volume=decimal_string(latest_price.volume),
            change_1d=optional_decimal(change_1d),
        ),
        returns={key: optional_decimal(value) for key, value in summary["returns"].items()},
        risk={key: optional_decimal(value) for key, value in summary["risk"].items()},
        technical=technical,
        rankings=rankings,
        filing_reactions=_filing_reactions(company, prices, filings),
    )


@app.get("/api/v1/compare", response_model=CompareOut)
def compare_companies(
    session: DbSession,
    cik: Annotated[list[str], Query(min_length=2, max_length=5)],
    metric: Annotated[list[str] | None, Query()] = None,
    frequency: Annotated[str, Query(pattern="^(annual|quarterly|ttm)$")] = "annual",
) -> CompareOut:
    unique_ciks = list(dict.fromkeys(normalize_cik(item) for item in cik))
    if not 2 <= len(unique_ciks) <= 5:
        raise HTTPException(status_code=422, detail="比較公司數必須介於 2 到 5 家")
    companies = [get_company_or_404(session, item) for item in unique_ciks]
    requested = metric or ["revenue", "net_income", "eps_diluted", "free_cash_flow", "roe"]
    definitions = {
        item.code: item
        for item in session.scalars(
            select(MetricDefinition).where(MetricDefinition.code.in_(requested))
        )
    }
    series: dict[str, dict[str, list[MetricPointOut]]] = {}
    for company in companies:
        values, revisions = latest_values(
            query_metric_values(session, company.id, frequency, requested, None, None)
        )
        company_series: dict[str, list[MetricPointOut]] = defaultdict(list)
        for value in values:
            key = (value.metric_code, value.frequency, value.period_end, value.unit)
            company_series[value.metric_code].append(
                point_out(value, definitions[value.metric_code], company.cik, revisions[key])
            )
        series[company.cik] = dict(company_series)
    return CompareOut(
        frequency=frequency,
        companies=[company_summary(company) for company in companies],
        series=series,
    )


@app.get("/api/v1/sync-runs", response_model=list[SyncRunOut])
def list_sync_runs(
    session: DbSession, limit: Annotated[int, Query(ge=1, le=100)] = 20
) -> list[SyncRun]:
    return list(
        session.scalars(
            select(SyncRun)
            .options(
                selectinload(SyncRun.price_items).selectinload(PriceSyncItem.instrument)
            )
            .order_by(SyncRun.created_at.desc())
            .limit(limit)
        )
    )


@app.post("/api/v1/sync-runs", response_model=SyncRunOut, status_code=status.HTTP_202_ACCEPTED)
def create_sync_run(payload: SyncRunCreate, session: DbSession) -> SyncRun:
    is_price_sync = payload.kind in {"prices", "price_company"}
    if is_price_sync and not settings.tiingo_is_configured:
        raise HTTPException(
            status_code=503,
            detail={"code": "tiingo_not_configured", "message": "請先設定 TIINGO_API_TOKEN"},
        )
    if not is_price_sync and not settings.sec_is_configured:
        raise HTTPException(
            status_code=503,
            detail="請先在 .env 設定有效的 SEC_USER_AGENT（產品名稱＋聯絡信箱）",
        )
    existing = session.scalar(
        select(SyncRun).where(
            SyncRun.kind == payload.kind,
            SyncRun.cik == payload.cik,
            SyncRun.status.in_(("pending", "running")),
        )
    )
    if existing:
        raise HTTPException(status_code=409, detail="相同同步工作已在佇列或執行中")
    run = SyncRun(
        id=str(uuid.uuid4()),
        kind=payload.kind,
        cik=payload.cik,
        status="pending",
        progress_current=0,
        message="等待 worker 執行",
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run
