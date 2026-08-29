import json
import os
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from company_facts.ingestion import bulk_upsert_facts, ingest_companyfacts_payload
from company_facts.models import CanonicalValue, Company, Concept, Fact

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="Set TEST_DATABASE_URL to run PostgreSQL integration tests.",
)
FIXTURES = Path(__file__).parent / "fixtures"


def test_postgres_partitioned_copy_is_idempotent_and_atomic() -> None:
    assert TEST_DATABASE_URL is not None
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    payload = json.loads((FIXTURES / "aapl_companyfacts.json").read_text(encoding="utf-8"))
    payload["cik"] = 9_999_999_999
    payload["entityName"] = "PostgreSQL Integration Fixture"

    with Session(engine) as session:
        try:
            company = ingest_companyfacts_payload(session, payload)
            first_fact_count = session.scalar(
                select(func.count()).select_from(Fact).where(Fact.company_id == company.id)
            )
            first_value_count = session.scalar(
                select(func.count())
                .select_from(CanonicalValue)
                .where(CanonicalValue.company_id == company.id)
            )
            assert first_fact_count and first_value_count

            ingest_companyfacts_payload(session, payload, company=company)
            assert (
                session.scalar(
                    select(func.count()).select_from(Fact).where(Fact.company_id == company.id)
                )
                == first_fact_count
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(CanonicalValue)
                    .where(CanonicalValue.company_id == company.id)
                )
                == first_value_count
            )

            partition_count = session.scalar(
                text(
                    """
                    SELECT count(*)
                    FROM pg_inherits i
                    JOIN pg_class c ON c.oid = i.inhrelid
                    WHERE c.relname LIKE 'facts_p%' AND c.relkind = 'r'
                    """
                )
            )
            assert partition_count == 16

            concept_id = session.scalar(
                select(Concept.id).where(
                    Concept.taxonomy == "us-gaap",
                    Concept.name == "Assets",
                )
            )
            assert concept_id is not None
            row = {
                "fingerprint": "f" * 64,
                "company_id": company.id,
                "concept_id": concept_id,
                "unit": "USD",
                "period_start": None,
                "period_end": date(2025, 1, 1),
                "value": Decimal(1),
                "accession": "9999999999-25-000001",
                "form": "10-K",
                "filed": date(2025, 2, 1),
                "fiscal_year": 2025,
                "fiscal_period": "FY",
                "frame": None,
                "source_run_id": None,
                "is_active": True,
            }
            invalid_row = {**row, "fingerprint": "e" * 64, "concept_id": 9_999_999_999}
            with pytest.raises(IntegrityError):
                bulk_upsert_facts(session, [row, invalid_row])
                session.commit()
            session.rollback()
            assert (
                session.scalar(
                    select(func.count()).select_from(Fact).where(Fact.company_id == company.id)
                )
                == first_fact_count
            )
        finally:
            session.rollback()
            session.execute(delete(Company).where(Company.cik == "9999999999"))
            session.commit()
    engine.dispose()
