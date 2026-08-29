from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import company_facts.main as main_module
from company_facts.db import Base, get_db
from company_facts.ingestion import sync_metric_registry
from company_facts.main import app
from company_facts.models import CanonicalValue, Company, Concept, Fact, Security


def make_client() -> TestClient:
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
