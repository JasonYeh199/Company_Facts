import json
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from company_facts.db import Base
from company_facts.ingestion import (
    ingest_companyfacts_payload,
    ingest_submissions_payload,
    upsert_universe,
)
from company_facts.models import CanonicalValue, Company, Fact, Filing, Security

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_ingestion_is_idempotent_and_builds_canonical(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        company = ingest_companyfacts_payload(session, fixture("aapl_companyfacts.json"), "run-1")
        first_count = session.query(Fact).count()
        canonical_count = session.query(CanonicalValue).count()
        assert company.supported
        assert first_count > 0
        assert canonical_count > 0
        ingest_companyfacts_payload(session, fixture("aapl_companyfacts.json"), "run-2", company)
        assert session.query(Fact).count() == first_count
        assert session.query(CanonicalValue).count() == canonical_count


def test_ifrs_company_is_retained_but_unsupported(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        company = ingest_companyfacts_payload(session, fixture("ifrs_companyfacts.json"))
        assert company.accounting_standard == "unsupported"
        assert company.supported is False
        assert session.scalar(select(Company).where(Company.cik == "0001046179")) is not None
        assert session.query(Fact).count() == 0


def test_submissions_tickers_activate_a_single_company_sync(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        company = Company(cik="0000320193", name="Apple Inc.", is_active=False)
        session.add(company)
        session.commit()

        ingest_submissions_payload(
            session,
            company,
            {
                "tickers": ["AAPL"],
                "exchanges": ["Nasdaq"],
                "filings": {"recent": {"accessionNumber": []}},
            },
        )

        assert company.is_active is True
        security = session.scalar(select(Security).where(Security.company_id == company.id))
        assert security is not None
        assert security.ticker == "AAPL"
        assert security.is_active is True


def test_submissions_filing_upsert_is_idempotent(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        company = Company(cik="0000320193", name="Apple Inc.", is_active=True)
        session.add(company)
        session.commit()
        payload = {
            "filings": {
                "recent": {
                    "accessionNumber": ["0000320193-25-000079", "0000320193-26-000001"],
                    "filingDate": ["2025-10-31", "2026-01-30"],
                    "reportDate": ["2025-09-27", "2025-12-27"],
                    "form": ["10-K", "10-Q"],
                    "primaryDocument": ["aapl-20250927.htm", "aapl-20251227.htm"],
                }
            }
        }

        assert ingest_submissions_payload(session, company, payload) == 2
        payload["filings"]["recent"]["primaryDocument"][0] = "amended.htm"
        assert ingest_submissions_payload(session, company, payload) == 2

        assert session.query(Filing).count() == 2
        filing = session.scalar(
            select(Filing).where(Filing.accession == "0000320193-25-000079")
        )
        assert filing is not None
        assert filing.primary_document == "amended.htm"


def test_universe_can_be_limited_to_selected_tickers(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Company(cik="0000789019", name="Microsoft Corp", is_active=True))
        session.commit()

        eligible = upsert_universe(
            session,
            {
                "fields": ["cik", "name", "ticker", "exchange"],
                "data": [
                    [320193, "Apple Inc.", "AAPL", "Nasdaq"],
                    [789019, "Microsoft Corp", "MSFT", "Nasdaq"],
                    [999999, "Example Fund", "FUND", "NYSE"],
                ],
            },
            {
                "fields": ["cik", "name", "ticker", "exchange"],
                "data": [[999999, "Example Fund", "FUND", "NYSE"]],
            },
            {"AAPL"},
        )

        assert eligible == {"0000320193"}
        apple = session.scalar(select(Company).where(Company.cik == "0000320193"))
        microsoft = session.scalar(select(Company).where(Company.cik == "0000789019"))
        assert apple is not None and apple.is_active is True
        assert microsoft is not None and microsoft.is_active is False
        assert session.scalar(select(Company).where(Company.cik == "0000999999")) is None
        active_security = session.scalar(
            select(Security).where(Security.company_id == apple.id, Security.is_active.is_(True))
        )
        assert active_security is not None
        assert active_security.ticker == "AAPL"
