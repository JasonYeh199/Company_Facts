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
    kind: Literal["bulk", "top100", "company"]
    cik: str | None = None

    @model_validator(mode="after")
    def validate_company_cik(self) -> SyncRunCreate:
        if self.kind == "company" and not self.cik:
            raise ValueError("company sync requires cik")
        if self.cik:
            digits = "".join(character for character in self.cik if character.isdigit())
            if not digits or len(digits) > 10:
                raise ValueError("invalid CIK")
            self.cik = digits.zfill(10)
        return self


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


class SetupStatus(BaseModel):
    sec_configured: bool
    database_connected: bool
    data_dir: str
    free_gib: float
    disk_requirement_gib: int = 60
    company_count: int
    supported_company_count: int
    latest_sync: SyncRunOut | None
