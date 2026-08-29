from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import company_facts.main as main_module
from company_facts.db import Base, get_db
from company_facts.ingestion import sync_metric_registry
from company_facts.main import app
from company_facts.models import (
    CanonicalValue,
    Company,
    Concept,
    DailyPrice,
    DailyPriceIndicator,
    Fact,
    PriceInstrument,
    PriceRank,
    PriceSyncItem,
    Security,
    SyncRun,
)
from company_facts.price_analysis import build_indicator_rows


def make_client(*, with_prices: bool = False) -> TestClient:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        sync_metric_registry(session)
        for cik, ticker, name, value in (
            ("0000320193", "AAPL", "Apple Inc.", 391035000000),
            ("0000789019", "MSFT", "Microsoft Corporation", 245122000000),
        ):
            company = Company(
                cik=cik,
                name=name,
                accounting_standard="us-gaap",
                supported=True,
                is_active=True,
            )
            session.add(company)
            session.flush()
            session.add(Security(company_id=company.id, ticker=ticker, exchange="Nasdaq"))
            session.add(
                CanonicalValue(
                    company_id=company.id,
                    metric_code="revenue",
                    frequency="annual",
                    period_start=date(2024, 1, 1),
                    period_end=date(2024, 12, 31),
                    fiscal_year=2024,
                    fiscal_period="FY",
                    value=Decimal(value),
                    unit="USD",
                    accession="0000320193-25-000001",
                    accession_key="0000320193-25-000001",
                    filed=date(2025, 2, 1),
                    form="10-K",
                    is_derived=False,
                    quality="reported",
                    lineage=[],
                    mapping_version="1.0.0",
                )
            )
        apple = session.query(Company).filter_by(cik="0000320193").one()
        concept = Concept(taxonomy="us-gaap", name="Assets", label="Assets")
        session.add(concept)
        session.flush()
        session.add(
            Fact(
                fingerprint="a" * 64,
                company_id=apple.id,
                concept_id=concept.id,
                unit="USD",
                period_start=None,
                period_end=date(2024, 12, 31),
                value=Decimal(100),
                accession="0000320193-25-000001",
                form="10-K",
                filed=date(2025, 2, 1),
                is_active=True,
            )
        )
        if with_prices:
            apple_security = (
                session.query(Security).filter_by(company_id=apple.id, ticker="AAPL").one()
            )
            instrument = PriceInstrument(
                company_id=apple.id,
                security_id=apple_security.id,
                provider="tiingo",
                provider_symbol="AAPL",
                is_primary=True,
                status="available",
                currency="USD",
                coverage_start=date(2025, 1, 1),
                coverage_end=date(2025, 10, 27),
                last_synced_at=datetime(2025, 10, 28, tzinfo=UTC),
            )
            session.add(instrument)
            session.flush()
            prices: list[DailyPrice] = []
            for index in range(300):
                close = Decimal(100 + index)
                row = DailyPrice(
                    instrument_id=instrument.id,
                    price_date=date(2025, 1, 1) + timedelta(days=index),
                    open=close,
                    high=close + 1,
                    low=close - 1,
                    close=close,
                    volume=Decimal(1_000_000 + index),
                    adj_open=close,
                    adj_high=close + 1,
                    adj_low=close - 1,
                    adj_close=close,
                    adj_volume=Decimal(1_000_000 + index),
                    dividend_cash=Decimal("0"),
                    split_factor=Decimal("1"),
                )
                session.add(row)
                prices.append(row)
            session.flush()
            session.add_all(DailyPriceIndicator(**row) for row in build_indicator_rows(prices))
            session.add(
                PriceRank(
                    as_of=date(2025, 10, 27),
                    instrument_id=instrument.id,
                    metric_code="return_1m",
                    value=Decimal("0.12"),
                    rank=1,
                    percentile=Decimal("1"),
                    universe_size=1,
                )
            )
            run = SyncRun(
                id="price-run",
                kind="prices",
                status="completed_with_errors",
                progress_current=1,
                progress_total=1,
            )
            session.add(run)
            session.flush()
            session.add(
                PriceSyncItem(
                    run_id=run.id,
                    instrument_id=instrument.id,
                    status="unsupported",
                    row_count=0,
                    error="provider unsupported",
                )
            )
        session.commit()

    def override_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def test_search_metrics_facts_and_compare_contracts() -> None:
    with make_client() as client:
        search = client.get("/api/v1/companies/search", params={"q": "AAPL"})
        assert search.status_code == 200
        assert search.json()[0]["cik"] == "0000320193"

        metrics = client.get(
            "/api/v1/companies/0000320193/metrics",
            params={"frequency": "annual", "metric": "revenue"},
        )
        assert metrics.status_code == 200
        point = metrics.json()["metrics"]["revenue"][0]
        assert point["value"] == "391035000000"
        assert point["source"]["url"].startswith("https://www.sec.gov/Archives/")

        facts = client.get("/api/v1/companies/0000320193/facts", params={"concept": "Assets"})
        assert facts.status_code == 200
        assert facts.json()["total"] == 1

        compare = client.get(
            "/api/v1/compare",
            params=[
                ("cik", "0000320193"),
                ("cik", "0000789019"),
                ("metric", "revenue"),
                ("frequency", "annual"),
            ],
        )
        assert compare.status_code == 200
        assert len(compare.json()["companies"]) == 2


def test_compare_limit_and_sync_configuration_errors(monkeypatch) -> None:
    monkeypatch.setattr(main_module.settings, "sec_user_agent", "")
    with make_client() as client:
        response = client.get("/api/v1/compare", params={"cik": "0000320193"})
        assert response.status_code == 422
        sync = client.post("/api/v1/sync-runs", json={"kind": "bulk"})
        assert sync.status_code == 503


def test_price_contracts_and_decimal_strings(monkeypatch) -> None:
    monkeypatch.setattr(main_module.settings, "tiingo_api_token", "test-token-123456789")
    with make_client(with_prices=True) as client:
        detail = client.get("/api/v1/companies/0000320193")
        assert detail.status_code == 200
        assert detail.json()["price_coverage"]["ticker"] == "AAPL"

        prices = client.get(
            "/api/v1/companies/0000320193/prices",
            params={"start_date": "2025-09-01", "end_date": "2025-10-27"},
        )
        assert prices.status_code == 200
        assert prices.json()["points"][-1]["close"] == "399"
        assert isinstance(prices.json()["points"][-1]["indicators"]["rsi_14"], str)

        analysis = client.get("/api/v1/companies/0000320193/price-analysis")
        assert analysis.status_code == 200
        body = analysis.json()
        assert body["latest"]["close"] == "399"
        assert isinstance(body["returns"]["return_1m"], str)
        assert body["rankings"][0]["rank"] == 1

        runs = client.get("/api/v1/sync-runs")
        assert runs.status_code == 200
        assert runs.json()[0]["price_items"][0] == {
            "ticker": "AAPL",
            "status": "unsupported",
            "requested_from": None,
            "requested_to": None,
            "row_count": 0,
            "error": "provider unsupported",
            "started_at": None,
            "completed_at": None,
        }


def test_price_api_requires_tiingo_configuration(monkeypatch) -> None:
    monkeypatch.setattr(main_module.settings, "tiingo_api_token", "")
    with make_client() as client:
        response = client.get("/api/v1/companies/0000320193/prices")
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "tiingo_not_configured"
