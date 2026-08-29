from __future__ import annotations

import gzip
import json
import re
from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session, selectinload

from .models import Company, MetricDefinition, SyncRun

ANNUAL_FROM = date(2019, 1, 1)
INTERIM_FROM = date(2023, 1, 1)
FACTS_PER_COMPANY = 250
ACCESSION_PATTERN = re.compile(r"^\d{10}-\d{2}-\d{6}$")


def _iso(value: date | datetime | None) -> str | None:
    if value is None:
        return None
    rendered = value.isoformat()
    return rendered.replace("+00:00", "Z")


def _decimal(value: Decimal) -> str:
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return _decimal(value)
    if isinstance(value, (date, datetime)):
        return _iso(value)
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _sec_url(cik: str, accession: str | None) -> str | None:
    if not accession or ACCESSION_PATTERN.fullmatch(accession) is None:
        return None
    return (
        f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
        f"{accession.replace('-', '')}/{accession}-index.html"
    )


def _write_json(path: Path, payload: Any) -> int:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    compressed = gzip.compress(encoded, compresslevel=9, mtime=0)
    target = path.with_suffix(f"{path.suffix}.gz")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(compressed)
    return len(compressed)


def _company_payload(company: Company) -> dict[str, Any]:
    return {
        "cik": company.cik,
        "name": company.name,
        "supported": company.supported,
        "accounting_standard": company.accounting_standard,
        "tickers": [
            {
                "ticker": security.ticker,
                "exchange": security.exchange,
                "is_active": security.is_active,
            }
            for security in sorted(
                (item for item in company.securities if item.is_active),
                key=lambda item: item.ticker,
            )
        ],
        "sic": company.sic,
        "fiscal_year_end": company.fiscal_year_end,
        "is_active": company.is_active,
        "last_synced_at": _iso(company.last_synced_at),
        "coverage_reason": None if company.supported else "首版只支援 US-GAAP",
    }


def _sync_payload(run: SyncRun | None, generated_at: datetime) -> dict[str, Any]:
    if run is None:
        return {
            "id": "vercel-snapshot",
            "kind": "top100",
            "cik": None,
            "status": "completed",
            "progress_current": 100,
            "progress_total": 100,
            "message": "Vercel 唯讀快照",
            "error": None,
            "source_etag": None,
            "created_at": _iso(generated_at),
            "started_at": _iso(generated_at),
            "completed_at": _iso(generated_at),
        }
    return {
        "id": run.id,
        "kind": run.kind,
        "cik": run.cik,
        "status": run.status,
        "progress_current": run.progress_current,
        "progress_total": run.progress_total,
        "message": f"{run.message or '同步完成'} · Vercel 唯讀快照",
        "error": run.error,
        "source_etag": run.source_etag,
        "created_at": _iso(run.created_at),
        "started_at": _iso(run.started_at),
        "completed_at": _iso(run.completed_at),
    }


def export_vercel_snapshot(
    session: Session,
    output_dir: Path,
    facts_per_company: int = FACTS_PER_COMPANY,
) -> dict[str, int]:
    generated_at = datetime.now(UTC)
    companies = list(
        session.scalars(
            select(Company)
            .options(selectinload(Company.securities))
            .where(Company.is_active.is_(True), Company.supported.is_(True))
            .order_by(Company.cik)
        )
    )
    company_by_id = {company.id: company for company in companies}
    company_payloads = {company.id: _company_payload(company) for company in companies}
    definitions = list(
        session.scalars(select(MetricDefinition).order_by(MetricDefinition.code))
    )
    definition_payloads = [
        {
            "code": item.code,
            "name_en": item.name_en,
            "name_zh": item.name_zh,
            "statement": item.statement,
        }
        for item in definitions
    ]
    latest_run = session.scalar(
        select(SyncRun)
        .where(SyncRun.kind == "top100", SyncRun.status == "completed")
        .order_by(SyncRun.completed_at.desc())
        .limit(1)
    )

    metrics: dict[int, dict[str, dict[str, list[dict[str, Any]]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )
    point_count = 0
    point_rows = session.execute(
        text(
            """
            WITH ranked AS (
                SELECT
                    cv.*,
                    count(*) OVER (
                        PARTITION BY cv.company_id, cv.metric_code, cv.frequency,
                                     cv.period_end, cv.unit
                    ) AS revision_count,
                    row_number() OVER (
                        PARTITION BY cv.company_id, cv.metric_code, cv.frequency,
                                     cv.period_end, cv.unit
                        ORDER BY
                            CASE WHEN cv.quality = 'ambiguous' THEN 1 ELSE 0 END,
                            cv.filed DESC NULLS LAST,
                            cv.accession DESC NULLS LAST
                    ) AS latest_rank
                FROM canonical_values AS cv
                JOIN companies AS company ON company.id = cv.company_id
                WHERE company.is_active IS TRUE
                  AND company.supported IS TRUE
                  AND (
                    (cv.frequency = 'annual' AND cv.period_end >= :annual_from)
                    OR (
                        cv.frequency IN ('quarterly', 'ttm')
                        AND cv.period_end >= :interim_from
                    )
                  )
            )
            SELECT
                ranked.*,
                definition.name_en,
                definition.name_zh,
                definition.statement
            FROM ranked
            JOIN metric_definitions AS definition
              ON definition.code = ranked.metric_code
            WHERE ranked.latest_rank = 1
              AND ranked.quality <> 'ambiguous'
            ORDER BY ranked.company_id, ranked.frequency, ranked.metric_code,
                     ranked.period_end
            """
        ),
        {"annual_from": ANNUAL_FROM, "interim_from": INTERIM_FROM},
    ).mappings()
    for row in point_rows:
        company = company_by_id.get(row["company_id"])
        if company is None:
            continue
        accession = row["accession"]
        lineage = [_jsonable(item) for item in (row["lineage"] or [])[:8]]
        point = {
            "metric": row["metric_code"],
            "name_en": row["name_en"],
            "name_zh": row["name_zh"],
            "statement": row["statement"],
            "frequency": row["frequency"],
            "period_start": _iso(row["period_start"]),
            "period_end": _iso(row["period_end"]),
            "fiscal_year": row["fiscal_year"],
            "fiscal_period": row["fiscal_period"],
            "value": _decimal(row["value"]),
            "unit": row["unit"],
            "is_derived": row["is_derived"],
            "quality": row["quality"],
            "revision_count": row["revision_count"],
            "source": {
                "accession": accession,
                "form": row["form"],
                "filed": _iso(row["filed"]),
                "url": _sec_url(company.cik, accession),
                "lineage": lineage,
            },
        }
        metrics[company.id][row["frequency"]][row["metric_code"]].append(point)
        point_count += 1

    facts: dict[int, list[dict[str, Any]]] = defaultdict(list)
    fact_rows = session.execute(
        text(
            """
            WITH ranked AS (
                SELECT
                    fact.*,
                    concept.taxonomy,
                    concept.name AS concept_name,
                    concept.label,
                    company.cik,
                    row_number() OVER (
                        PARTITION BY fact.company_id
                        ORDER BY fact.period_end DESC, fact.filed DESC,
                                 fact.fingerprint
                    ) AS company_rank
                FROM facts AS fact
                JOIN concepts AS concept ON concept.id = fact.concept_id
                JOIN companies AS company ON company.id = fact.company_id
                WHERE fact.is_active IS TRUE
                  AND company.is_active IS TRUE
                  AND company.supported IS TRUE
            )
            SELECT * FROM ranked
            WHERE company_rank <= :facts_per_company
            ORDER BY company_id, company_rank
            """
        ),
        {"facts_per_company": facts_per_company},
    ).mappings()
    fact_count = 0
    for row in fact_rows:
        facts[row["company_id"]].append(
            {
                "id": row["fingerprint"],
                "taxonomy": row["taxonomy"],
                "concept": row["concept_name"],
                "label": row["label"],
                "unit": row["unit"],
                "period_start": _iso(row["period_start"]),
                "period_end": _iso(row["period_end"]),
                "value": _decimal(row["value"]),
                "accession": row["accession"],
                "form": row["form"],
                "filed": _iso(row["filed"]),
                "fiscal_year": row["fiscal_year"],
                "fiscal_period": row["fiscal_period"],
                "frame": row["frame"],
                "source_url": _sec_url(row["cik"], row["accession"]) or "",
            }
        )
        fact_count += 1

    sync_payload = _sync_payload(latest_run, generated_at)
    index_payload = {
        "snapshot": {
            "generated_at": _iso(generated_at),
            "annual_from": ANNUAL_FROM.isoformat(),
            "interim_from": INTERIM_FROM.isoformat(),
            "facts_per_company": facts_per_company,
            "read_only": True,
        },
        "companies": list(company_payloads.values()),
        "definitions": definition_payloads,
        "sync_runs": [sync_payload],
    }
    total_bytes = _write_json(output_dir / "index.json", index_payload)
    for company in companies:
        company_metrics = {
            frequency: dict(metric_groups)
            for frequency, metric_groups in metrics.get(company.id, {}).items()
        }
        total_bytes += _write_json(
            output_dir / "companies" / f"{company.cik}.json",
            {
                "company": company_payloads[company.id],
                "metrics": company_metrics,
                "facts": facts.get(company.id, []),
            },
        )
    return {
        "companies": len(companies),
        "points": point_count,
        "facts": fact_count,
        "bytes": total_bytes,
    }
