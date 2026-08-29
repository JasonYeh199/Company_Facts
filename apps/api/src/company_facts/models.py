from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

PK_TYPE = BigInteger().with_variant(Integer, "sqlite")


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Company(TimestampMixin, Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(PK_TYPE, primary_key=True, autoincrement=True)
    cik: Mapped[str] = mapped_column(String(10), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(300), index=True)
    sic: Mapped[str | None] = mapped_column(String(8))
    fiscal_year_end: Mapped[str | None] = mapped_column(String(4))
    accounting_standard: Mapped[str | None] = mapped_column(String(32))
    supported: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    securities: Mapped[list[Security]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )
    price_instruments: Mapped[list[PriceInstrument]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )


class Security(TimestampMixin, Base):
    __tablename__ = "securities"
    __table_args__ = (UniqueConstraint("company_id", "ticker", "exchange"),)

    id: Mapped[int] = mapped_column(PK_TYPE, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    exchange: Mapped[str | None] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    company: Mapped[Company] = relationship(back_populates="securities")
    price_instruments: Mapped[list[PriceInstrument]] = relationship(back_populates="security")


class Filing(Base):
    __tablename__ = "filings"
    __table_args__ = (UniqueConstraint("company_id", "accession"),)

    id: Mapped[int] = mapped_column(PK_TYPE, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    accession: Mapped[str] = mapped_column(String(32), index=True)
    form: Mapped[str] = mapped_column(String(20), index=True)
    filed: Mapped[date] = mapped_column(Date, index=True)
    report_date: Mapped[date | None] = mapped_column(Date)
    primary_document: Mapped[str | None] = mapped_column(String(300))
    is_amendment: Mapped[bool] = mapped_column(Boolean, default=False)


class Concept(Base):
    __tablename__ = "concepts"
    __table_args__ = (UniqueConstraint("taxonomy", "name"),)

    id: Mapped[int] = mapped_column(PK_TYPE, primary_key=True, autoincrement=True)
    taxonomy: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(300), index=True)
    label: Mapped[str | None] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)


class Fact(Base):
    __tablename__ = "facts"
    __table_args__ = (
        Index("ix_facts_company_concept_end", "company_id", "concept_id", "period_end"),
        Index("ix_facts_company_accession", "company_id", "accession"),
        {"postgresql_partition_by": "HASH (company_id)"},
    )

    fingerprint: Mapped[str] = mapped_column(String(64), primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    concept_id: Mapped[int] = mapped_column(ForeignKey("concepts.id"), index=True)
    unit: Mapped[str] = mapped_column(String(64), index=True)
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date, index=True)
    value: Mapped[Decimal] = mapped_column(Numeric)
    accession: Mapped[str] = mapped_column(String(32), index=True)
    form: Mapped[str] = mapped_column(String(20), index=True)
    filed: Mapped[date] = mapped_column(Date, index=True)
    fiscal_year: Mapped[int | None] = mapped_column(Integer)
    fiscal_period: Mapped[str | None] = mapped_column(String(12))
    frame: Mapped[str | None] = mapped_column(String(24))
    source_run_id: Mapped[str | None] = mapped_column(String(36), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class MetricDefinition(Base):
    __tablename__ = "metric_definitions"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    name_en: Mapped[str] = mapped_column(String(120))
    name_zh: Mapped[str] = mapped_column(String(120))
    statement: Mapped[str] = mapped_column(String(32), index=True)
    value_kind: Mapped[str] = mapped_column(String(16))
    expected_unit: Mapped[str | None] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(Text)
    is_derived: Mapped[bool] = mapped_column(Boolean, default=False)


class MetricMapping(Base):
    __tablename__ = "metric_mappings"
    __table_args__ = (UniqueConstraint("metric_code", "taxonomy", "concept", "version"),)

    id: Mapped[int] = mapped_column(PK_TYPE, primary_key=True, autoincrement=True)
    metric_code: Mapped[str] = mapped_column(ForeignKey("metric_definitions.code"), index=True)
    taxonomy: Mapped[str] = mapped_column(String(64))
    concept: Mapped[str] = mapped_column(String(300))
    priority: Mapped[int] = mapped_column(Integer)
    version: Mapped[str] = mapped_column(String(32))


class CanonicalValue(Base):
    __tablename__ = "canonical_values"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "metric_code",
            "frequency",
            "period_end",
            "unit",
            "accession_key",
            "mapping_version",
        ),
        Index(
            "ix_canonical_company_metric_frequency_end",
            "company_id",
            "metric_code",
            "frequency",
            "period_end",
        ),
    )

    id: Mapped[int] = mapped_column(PK_TYPE, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    metric_code: Mapped[str] = mapped_column(ForeignKey("metric_definitions.code"), index=True)
    frequency: Mapped[str] = mapped_column(String(16), index=True)
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date, index=True)
    fiscal_year: Mapped[int | None] = mapped_column(Integer)
    fiscal_period: Mapped[str | None] = mapped_column(String(12))
    value: Mapped[Decimal] = mapped_column(Numeric)
    unit: Mapped[str] = mapped_column(String(64))
    accession: Mapped[str | None] = mapped_column(String(32))
    accession_key: Mapped[str] = mapped_column(String(96))
    filed: Mapped[date | None] = mapped_column(Date)
    form: Mapped[str | None] = mapped_column(String(20))
    is_derived: Mapped[bool] = mapped_column(Boolean, default=False)
    quality: Mapped[str] = mapped_column(String(24), default="reported")
    lineage: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    mapping_version: Mapped[str] = mapped_column(String(32))


class SyncRun(Base):
    __tablename__ = "sync_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kind: Mapped[str] = mapped_column(String(24), index=True)
    cik: Mapped[str | None] = mapped_column(String(10), index=True)
    status: Mapped[str] = mapped_column(String(24), index=True, default="pending")
    progress_current: Mapped[int] = mapped_column(Integer, default=0)
    progress_total: Mapped[int | None] = mapped_column(Integer)
    message: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    source_etag: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    price_items: Mapped[list[PriceSyncItem]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class PriceInstrument(TimestampMixin, Base):
    __tablename__ = "price_instruments"
    __table_args__ = (
        UniqueConstraint("provider", "provider_symbol"),
        UniqueConstraint("company_id", "is_primary"),
    )

    id: Mapped[int] = mapped_column(PK_TYPE, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(24), default="tiingo")
    provider_symbol: Mapped[str] = mapped_column(String(32), index=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    currency: Mapped[str] = mapped_column(String(12), default="USD")
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    coverage_start: Mapped[date | None] = mapped_column(Date)
    coverage_end: Mapped[date | None] = mapped_column(Date)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)

    company: Mapped[Company] = relationship(back_populates="price_instruments")
    security: Mapped[Security] = relationship(back_populates="price_instruments")
    prices: Mapped[list[DailyPrice]] = relationship(
        back_populates="instrument", cascade="all, delete-orphan"
    )
    sync_items: Mapped[list[PriceSyncItem]] = relationship(back_populates="instrument")


class DailyPrice(Base):
    __tablename__ = "daily_prices"
    __table_args__ = (Index("ix_daily_prices_instrument_date", "instrument_id", "price_date"),)

    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("price_instruments.id", ondelete="CASCADE"), primary_key=True
    )
    price_date: Mapped[date] = mapped_column(Date, primary_key=True, index=True)
    open: Mapped[Decimal] = mapped_column(Numeric)
    high: Mapped[Decimal] = mapped_column(Numeric)
    low: Mapped[Decimal] = mapped_column(Numeric)
    close: Mapped[Decimal] = mapped_column(Numeric)
    volume: Mapped[Decimal] = mapped_column(Numeric)
    adj_open: Mapped[Decimal] = mapped_column(Numeric)
    adj_high: Mapped[Decimal] = mapped_column(Numeric)
    adj_low: Mapped[Decimal] = mapped_column(Numeric)
    adj_close: Mapped[Decimal] = mapped_column(Numeric)
    adj_volume: Mapped[Decimal] = mapped_column(Numeric)
    dividend_cash: Mapped[Decimal] = mapped_column(Numeric, default=Decimal("0"))
    split_factor: Mapped[Decimal] = mapped_column(Numeric, default=Decimal("1"))
    source_run_id: Mapped[str | None] = mapped_column(String(36), index=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    instrument: Mapped[PriceInstrument] = relationship(back_populates="prices")
    indicator: Mapped[DailyPriceIndicator | None] = relationship(
        back_populates="price", cascade="all, delete-orphan", uselist=False
    )


class DailyPriceIndicator(Base):
    __tablename__ = "daily_price_indicators"

    instrument_id: Mapped[int] = mapped_column(PK_TYPE, primary_key=True)
    price_date: Mapped[date] = mapped_column(Date, primary_key=True, index=True)
    daily_return: Mapped[Decimal | None] = mapped_column(Numeric)
    log_return: Mapped[Decimal | None] = mapped_column(Numeric)
    sma_20: Mapped[Decimal | None] = mapped_column(Numeric)
    sma_50: Mapped[Decimal | None] = mapped_column(Numeric)
    sma_200: Mapped[Decimal | None] = mapped_column(Numeric)
    ema_12: Mapped[Decimal | None] = mapped_column(Numeric)
    ema_26: Mapped[Decimal | None] = mapped_column(Numeric)
    rsi_14: Mapped[Decimal | None] = mapped_column(Numeric)
    macd: Mapped[Decimal | None] = mapped_column(Numeric)
    macd_signal: Mapped[Decimal | None] = mapped_column(Numeric)
    macd_histogram: Mapped[Decimal | None] = mapped_column(Numeric)
    bollinger_mid: Mapped[Decimal | None] = mapped_column(Numeric)
    bollinger_upper: Mapped[Decimal | None] = mapped_column(Numeric)
    bollinger_lower: Mapped[Decimal | None] = mapped_column(Numeric)
    drawdown: Mapped[Decimal | None] = mapped_column(Numeric)
    volume_average_20: Mapped[Decimal | None] = mapped_column(Numeric)
    volume_ratio_20: Mapped[Decimal | None] = mapped_column(Numeric)

    __table_args__ = (
        ForeignKeyConstraint(
            ["instrument_id", "price_date"],
            ["daily_prices.instrument_id", "daily_prices.price_date"],
            ondelete="CASCADE",
        ),
    )

    price: Mapped[DailyPrice] = relationship(back_populates="indicator")


class PriceRank(Base):
    __tablename__ = "price_ranks"
    __table_args__ = (
        UniqueConstraint("as_of", "instrument_id", "metric_code"),
        Index("ix_price_ranks_instrument_as_of", "instrument_id", "as_of"),
    )

    id: Mapped[int] = mapped_column(PK_TYPE, primary_key=True, autoincrement=True)
    as_of: Mapped[date] = mapped_column(Date, index=True)
    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("price_instruments.id", ondelete="CASCADE"), index=True
    )
    metric_code: Mapped[str] = mapped_column(String(32), index=True)
    value: Mapped[Decimal] = mapped_column(Numeric)
    rank: Mapped[int] = mapped_column(Integer)
    percentile: Mapped[Decimal] = mapped_column(Numeric)
    universe_size: Mapped[int] = mapped_column(Integer)


class PriceSyncItem(Base):
    __tablename__ = "price_sync_items"
    __table_args__ = (UniqueConstraint("run_id", "instrument_id"),)

    id: Mapped[int] = mapped_column(PK_TYPE, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("sync_runs.id", ondelete="CASCADE"), index=True
    )
    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("price_instruments.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    requested_from: Mapped[date | None] = mapped_column(Date)
    requested_to: Mapped[date | None] = mapped_column(Date)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    run: Mapped[SyncRun] = relationship(back_populates="price_items")
    instrument: Mapped[PriceInstrument] = relationship(back_populates="sync_items")

    @property
    def ticker(self) -> str:
        return self.instrument.provider_symbol
