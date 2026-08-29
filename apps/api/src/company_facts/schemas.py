from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SecurityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ticker: str
    exchange: str | None
    is_active: bool


class CompanySummary(BaseModel):
    cik: str
    name: str
    supported: bool
    accounting_standard: str | None
    tickers: list[SecurityOut]


class CompanyDetail(CompanySummary):
    sic: str | None
    fiscal_year_end: str | None
    is_active: bool
    last_synced_at: datetime | None
    coverage_reason: str | None = None
    price_coverage: PriceCoverageOut | None = None


class PriceCoverageOut(BaseModel):
    ticker: str | None
    status: str
    start_date: date | None
    end_date: date | None
    last_synced_at: datetime | None
    reason: str | None = None


class SourceOut(BaseModel):
    accession: str | None
    form: str | None
    filed: date | None
    url: str | None
    lineage: list[dict[str, Any]] = Field(default_factory=list)


class MetricPointOut(BaseModel):
    metric: str
    name_en: str
    name_zh: str
    statement: str
    frequency: str
    period_start: date | None
    period_end: date
    fiscal_year: int | None
    fiscal_period: str | None
    value: str
    unit: str
    is_derived: bool
    quality: str
    revision_count: int = 1
    source: SourceOut


class MetricSeriesOut(BaseModel):
    company: CompanySummary
    frequency: str
    metrics: dict[str, list[MetricPointOut]]
    unavailable: list[str] = Field(default_factory=list)


class StatementOut(BaseModel):
    company: CompanySummary
    statement: str
    frequency: str
    metrics: list[dict[str, Any]]


class FactOut(BaseModel):
    id: str
    taxonomy: str
    concept: str
    label: str | None
    unit: str
    period_start: date | None
    period_end: date
    value: str
    accession: str
    form: str
    filed: date
    fiscal_year: int | None
    fiscal_period: str | None
    frame: str | None
    source_url: str


class FactsPage(BaseModel):
    items: list[FactOut]
    total: int
    limit: int
    offset: int


class CompareOut(BaseModel):
    frequency: str
    companies: list[CompanySummary]
    series: dict[str, dict[str, list[MetricPointOut]]]


class SyncRunCreate(BaseModel):
    kind: Literal["bulk", "top100", "company", "prices", "price_company"]
    cik: str | None = None

    @model_validator(mode="after")
    def validate_company_cik(self) -> SyncRunCreate:
        if self.kind in {"company", "price_company"} and not self.cik:
            raise ValueError("company sync requires cik")
        if self.cik:
            digits = "".join(character for character in self.cik if character.isdigit())
            if not digits or len(digits) > 10:
                raise ValueError("invalid CIK")
            self.cik = digits.zfill(10)
        return self


class PriceSyncItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ticker: str
    status: str
    requested_from: date | None
    requested_to: date | None
    row_count: int
    error: str | None
    started_at: datetime | None
    completed_at: datetime | None


class SyncRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: str
    cik: str | None
    status: str
    progress_current: int
    progress_total: int | None
    message: str | None
    error: str | None
    source_etag: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    price_items: list[PriceSyncItemOut] = Field(default_factory=list)


class SetupStatus(BaseModel):
    sec_configured: bool
    database_connected: bool
    data_dir: str
    free_gib: float
    disk_requirement_gib: int = 60
    company_count: int
    supported_company_count: int
    latest_sync: SyncRunOut | None
    tiingo_configured: bool = False
    price_company_count: int = 0
    latest_price_date: date | None = None
    latest_price_sync: SyncRunOut | None = None


class PriceIndicatorOut(BaseModel):
    daily_return: str | None = None
    log_return: str | None = None
    sma_20: str | None = None
    sma_50: str | None = None
    sma_200: str | None = None
    ema_12: str | None = None
    ema_26: str | None = None
    rsi_14: str | None = None
    macd: str | None = None
    macd_signal: str | None = None
    macd_histogram: str | None = None
    bollinger_mid: str | None = None
    bollinger_upper: str | None = None
    bollinger_lower: str | None = None
    drawdown: str | None = None
    volume_average_20: str | None = None
    volume_ratio_20: str | None = None


class PricePointOut(BaseModel):
    date: date
    open: str
    high: str
    low: str
    close: str
    volume: str
    adj_open: str
    adj_high: str
    adj_low: str
    adj_close: str
    adj_volume: str
    dividend_cash: str
    split_factor: str
    indicators: PriceIndicatorOut


class PriceEventOut(BaseModel):
    date: date
    type: Literal["dividend", "split", "filing"]
    label: str
    value: str | None = None
    accession: str | None = None
    url: str | None = None


class PriceSeriesOut(BaseModel):
    company: CompanySummary
    ticker: str
    currency: str
    start_date: date
    end_date: date
    points: list[PricePointOut]
    events: list[PriceEventOut]


class LatestPriceOut(BaseModel):
    date: date
    close: str
    adj_close: str
    volume: str
    change_1d: str | None = None


class PriceRankOut(BaseModel):
    metric: str
    value: str
    rank: int
    percentile: str
    universe_size: int
    as_of: date
    neighbors: list[PriceRankPeerOut] = Field(default_factory=list)


class PriceRankPeerOut(BaseModel):
    ticker: str
    company_name: str
    rank: int
    value: str


class FilingReactionOut(BaseModel):
    filed: date
    form: str
    accession: str
    url: str | None
    return_1d: str | None = None
    return_5d: str | None = None
    return_20d: str | None = None


class PriceAnalysisOut(BaseModel):
    company: CompanySummary
    ticker: str
    as_of: date
    latest: LatestPriceOut
    returns: dict[str, str | None]
    risk: dict[str, str | None]
    technical: dict[str, str | None]
    rankings: list[PriceRankOut]
    filing_reactions: list[FilingReactionOut]
