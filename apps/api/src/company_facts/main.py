from __future__ import annotations

import shutil
import uuid
from collections import Counter, defaultdict
from collections.abc import Iterable
from contextlib import asynccontextmanager
from datetime import date
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from .config import get_settings
from .db import get_db
from .metrics import METRICS_BY_CODE
from .models import CanonicalValue, Company, Concept, Fact, MetricDefinition, Security, SyncRun
from .schemas import (
    CompanyDetail,
    CompanySummary,
    CompareOut,
    FactOut,
    FactsPage,
    MetricPointOut,
    MetricSeriesOut,
    SecurityOut,
    SetupStatus,
    SourceOut,
    StatementOut,
    SyncRunCreate,
    SyncRunOut,
)

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
        database_connected = True
    except SQLAlchemyError:
        session.rollback()
        company_count = 0
        supported_count = 0
        latest = None
        database_connected = False
    return SetupStatus(
        sec_configured=settings.sec_is_configured,
        database_connected=database_connected,
        data_dir=str(settings.data_dir),
        free_gib=round(free, 1),
        company_count=company_count,
        supported_company_count=supported_count,
        latest_sync=SyncRunOut.model_validate(latest) if latest else None,
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
    return list(session.scalars(select(SyncRun).order_by(SyncRun.created_at.desc()).limit(limit)))


@app.post("/api/v1/sync-runs", response_model=SyncRunOut, status_code=status.HTTP_202_ACCEPTED)
def create_sync_run(payload: SyncRunCreate, session: DbSession) -> SyncRun:
    if not settings.sec_is_configured:
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
