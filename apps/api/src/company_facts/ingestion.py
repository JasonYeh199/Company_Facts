from __future__ import annotations

import hashlib
import json
import re
import shutil
import zipfile
from collections.abc import Iterable
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select, text, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .db import SessionLocal
from .metrics import ALL_METRICS, BASE_METRICS, MAPPING_VERSION
from .models import (
    CanonicalValue,
    Company,
    Concept,
    Fact,
    Filing,
    MetricDefinition,
    MetricMapping,
    Security,
    SyncRun,
)
from .normalization import RawFact, decimal_value, normalize_all
from .sec_client import URLS, DownloadMetadata, SecClient
from .top_companies import TOP100_AS_OF, TOP100_TICKERS

CIK_PATTERN = re.compile(r"CIK(\d{10})")
MIN_FREE_BYTES = 60 * 1024**3


def _parse_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _cik(value: object) -> str:
    return str(value).zfill(10)


def _fact_fingerprint(
    company_id: int,
    taxonomy: str,
    concept: str,
    unit: str,
    item: dict[str, Any],
) -> str:
    payload = "|".join(
        (
            str(company_id),
            taxonomy,
            concept,
            unit,
            str(item.get("start") or ""),
            str(item.get("end") or ""),
            str(item.get("val")),
            str(item.get("accn") or ""),
            str(item.get("filed") or ""),
            str(item.get("form") or ""),
        )
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def sync_metric_registry(session: Session) -> None:
    for spec in ALL_METRICS:
        current = session.get(MetricDefinition, spec.code)
        values = {
            "name_en": spec.name_en,
            "name_zh": spec.name_zh,
            "statement": spec.statement,
            "value_kind": spec.value_kind,
            "expected_unit": spec.unit_kind,
            "description": spec.description,
            "is_derived": spec.derived,
        }
        if current:
            for key, value in values.items():
                setattr(current, key, value)
        else:
            session.add(MetricDefinition(code=spec.code, **values))
    session.flush()
    session.execute(delete(MetricMapping).where(MetricMapping.version == MAPPING_VERSION))
    for spec in BASE_METRICS:
        for priority, concept in enumerate(spec.concepts):
            session.add(
                MetricMapping(
                    metric_code=spec.code,
                    taxonomy="us-gaap",
                    concept=concept,
                    priority=priority,
                    version=MAPPING_VERSION,
                )
            )


def parse_ticker_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    fields = payload.get("fields") or []
    return [dict(zip(fields, row, strict=False)) for row in payload.get("data") or []]


def upsert_universe(
    session: Session,
    exchange_payload: dict[str, Any],
    fund_payload: dict[str, Any],
    ticker_filter: set[str] | frozenset[str] | None = None,
) -> set[str]:
    fund_ciks = {_cik(row.get("cik")) for row in parse_ticker_rows(fund_payload)}
    exchange_rows = [
        row
        for row in parse_ticker_rows(exchange_payload)
        if row.get("ticker")
        and row.get("exchange")
        and _cik(row.get("cik")) not in fund_ciks
        and (
            ticker_filter is None
            or str(row.get("ticker")).upper() in ticker_filter
        )
    ]
    session.execute(update(Company).values(is_active=False))
    session.execute(update(Security).values(is_active=False))
    eligible_ciks: set[str] = set()
    for row in exchange_rows:
        cik = _cik(row["cik"])
        eligible_ciks.add(cik)
        company = session.scalar(select(Company).where(Company.cik == cik))
        if company is None:
            company = Company(cik=cik, name=str(row["name"]), is_active=True)
            session.add(company)
            session.flush()
        else:
            company.name = str(row["name"])
            company.is_active = True
        ticker = str(row["ticker"]).upper()
        exchange = str(row["exchange"])
        security = session.scalar(
            select(Security).where(
                Security.company_id == company.id,
                Security.ticker == ticker,
                Security.exchange == exchange,
            )
        )
        if security:
            security.is_active = True
        else:
            session.add(
                Security(company_id=company.id, ticker=ticker, exchange=exchange, is_active=True)
            )
    session.commit()
    return eligible_ciks


def _get_concept_id(
    session: Session,
    cache: dict[tuple[str, str], int],
    taxonomy: str,
    name: str,
    payload: dict[str, Any],
) -> int:
    key = (taxonomy, name)
    if key in cache:
        return cache[key]
    concept = session.scalar(
        select(Concept).where(Concept.taxonomy == taxonomy, Concept.name == name)
    )
    if concept is None:
        concept = Concept(
            taxonomy=taxonomy,
            name=name,
            label=payload.get("label"),
            description=payload.get("description"),
        )
        session.add(concept)
        session.flush()
    cache[key] = concept.id
    return concept.id


def ingest_companyfacts_payload(
    session: Session,
    payload: dict[str, Any],
    run_id: str | None = None,
    company: Company | None = None,
    concept_id_cache: dict[tuple[str, str], int] | None = None,
) -> Company:
    cik = _cik(payload["cik"])
    company = company or session.scalar(select(Company).where(Company.cik == cik))
    if company is None:
        company = Company(cik=cik, name=payload.get("entityName") or cik, is_active=False)
        session.add(company)
        session.flush()
    company.name = payload.get("entityName") or company.name
    company.accounting_standard = (
        "us-gaap" if "us-gaap" in payload.get("facts", {}) else "unsupported"
    )
    company.supported = company.accounting_standard == "us-gaap"
    company.last_synced_at = datetime.now(UTC)
    if not company.supported:
        session.execute(update(Fact).where(Fact.company_id == company.id).values(is_active=False))
        session.execute(delete(CanonicalValue).where(CanonicalValue.company_id == company.id))
        session.commit()
        return company

    concept_cache = concept_id_cache if concept_id_cache is not None else {}
    fact_rows: list[dict[str, Any]] = []
    for taxonomy, concepts in payload.get("facts", {}).items():
        for concept_name, concept_payload in concepts.items():
            concept_id = _get_concept_id(
                session,
                concept_cache,
                taxonomy,
                concept_name,
                concept_payload,
            )
            for unit, items in (concept_payload.get("units") or {}).items():
                for item in items:
                    if not item.get("end") or not item.get("accn") or not item.get("filed"):
                        continue
                    fingerprint = _fact_fingerprint(company.id, taxonomy, concept_name, unit, item)
                    try:
                        value = decimal_value(item.get("val"))
                    except ValueError:
                        continue
                    fact_rows.append(
                        {
                            "fingerprint": fingerprint,
                            "company_id": company.id,
                            "concept_id": concept_id,
                            "unit": unit,
                            "period_start": _parse_date(item.get("start")),
                            "period_end": _parse_date(item["end"]),
                            "value": value,
                            "accession": item["accn"],
                            "form": item.get("form") or "",
                            "filed": _parse_date(item["filed"]),
                            "fiscal_year": item.get("fy"),
                            "fiscal_period": item.get("fp"),
                            "frame": item.get("frame"),
                            "source_run_id": run_id,
                            "is_active": True,
                        }
                    )
    changed_count = bulk_upsert_facts(session, fact_rows, company.id)
    session.commit()
    current_canonical = session.scalar(
        select(CanonicalValue.id)
        .where(
            CanonicalValue.company_id == company.id,
            CanonicalValue.mapping_version == MAPPING_VERSION,
        )
        .limit(1)
    )
    if changed_count == 0 and current_canonical is not None:
        return company
    rebuild_canonical_values(session, company)
    return company


def bulk_upsert_facts(
    session: Session,
    rows: list[dict[str, Any]],
    company_id: int | None = None,
) -> int:
    company_id = company_id or (rows[0]["company_id"] if rows else None)
    if company_id is None:
        return 0
    if session.bind and session.bind.dialect.name == "postgresql":
        columns = (
            "fingerprint",
            "company_id",
            "concept_id",
            "unit",
            "period_start",
            "period_end",
            "value",
            "accession",
            "form",
            "filed",
            "fiscal_year",
            "fiscal_period",
            "frame",
            "source_run_id",
            "is_active",
        )
        session.execute(
            text("CREATE TEMP TABLE fact_stage (LIKE facts INCLUDING DEFAULTS) ON COMMIT DROP")
        )
        if rows:
            connection = session.connection().connection.driver_connection
            with connection.cursor().copy(
                f"COPY fact_stage ({', '.join(columns)}) FROM STDIN"
            ) as copy:
                for row in rows:
                    copy.write_row(tuple(row[column] for column in columns))
            session.execute(
                text("CREATE INDEX fact_stage_identity_idx ON fact_stage (company_id, fingerprint)")
            )
            session.execute(text("ANALYZE fact_stage"))
        column_list = ", ".join(columns)
        changed_count = session.scalar(
            text(
                f"""
                WITH changed AS (
                    INSERT INTO facts ({column_list})
                    SELECT {column_list} FROM fact_stage
                    ON CONFLICT (fingerprint, company_id) DO UPDATE
                    SET is_active = TRUE, source_run_id = EXCLUDED.source_run_id
                    WHERE facts.is_active IS DISTINCT FROM TRUE
                    RETURNING 1
                )
                SELECT count(*) FROM changed
                """
            )
        )
        deactivated = session.execute(
            text(
                """
                UPDATE facts AS target
                SET is_active = FALSE
                WHERE target.company_id = :company_id
                  AND target.is_active IS TRUE
                  AND NOT EXISTS (
                      SELECT 1 FROM fact_stage AS source
                      WHERE source.company_id = target.company_id
                        AND source.fingerprint = target.fingerprint
                  )
                """
            ),
            {"company_id": company_id},
        ).rowcount
        return int(changed_count or 0) + max(deactivated or 0, 0)
    existing = {
        fingerprint: is_active
        for fingerprint, is_active in session.execute(
            select(Fact.fingerprint, Fact.is_active).where(Fact.company_id == company_id)
        )
    }
    changed_count = 0
    incoming = {row["fingerprint"] for row in rows}
    for row in rows:
        if row["fingerprint"] in existing:
            if not existing[row["fingerprint"]]:
                session.execute(
                    update(Fact)
                    .where(
                        Fact.company_id == row["company_id"],
                        Fact.fingerprint == row["fingerprint"],
                    )
                    .values(is_active=True, source_run_id=row["source_run_id"])
                )
                changed_count += 1
        else:
            session.add(Fact(**row))
            changed_count += 1
    stale = [
        fingerprint
        for fingerprint, active in existing.items()
        if active and fingerprint not in incoming
    ]
    if stale:
        session.execute(
            update(Fact)
            .where(Fact.company_id == company_id, Fact.fingerprint.in_(stale))
            .values(is_active=False)
        )
        changed_count += len(stale)
    return changed_count


def rebuild_canonical_values(session: Session, company: Company) -> int:
    if session.get(MetricDefinition, "revenue") is None:
        sync_metric_registry(session)
    rows = session.execute(
        select(Fact, Concept)
        .join(Concept, Fact.concept_id == Concept.id)
        .where(Fact.company_id == company.id, Fact.is_active.is_(True))
    ).all()
    raw = [
        RawFact(
            id=fact.fingerprint,
            taxonomy=concept.taxonomy,
            concept=concept.name,
            unit=fact.unit,
            value=Decimal(fact.value),
            period_start=fact.period_start,
            period_end=fact.period_end,
            accession=fact.accession,
            form=fact.form,
            filed=fact.filed,
            fiscal_year=fact.fiscal_year,
            fiscal_period=fact.fiscal_period,
            frame=fact.frame,
        )
        for fact, concept in rows
    ]
    normalized = normalize_all(raw)
    session.execute(delete(CanonicalValue).where(CanonicalValue.company_id == company.id))
    for point in normalized:
        session.add(
            CanonicalValue(
                company_id=company.id,
                metric_code=point.metric_code,
                frequency=point.frequency,
                period_start=point.period_start,
                period_end=point.period_end,
                fiscal_year=point.fiscal_year,
                fiscal_period=point.fiscal_period,
                value=point.value,
                unit=point.unit,
                accession=point.accession,
                accession_key=point.accession_key,
                filed=point.filed,
                form=point.form,
                is_derived=point.is_derived,
                quality=point.quality,
                lineage=point.lineage,
                mapping_version=point.mapping_version,
            )
        )
    session.commit()
    return len(normalized)


def _columnar_rows(payload: dict[str, Any]) -> Iterable[dict[str, Any]]:
    recent = payload.get("filings", {}).get("recent") if "filings" in payload else payload
    if not isinstance(recent, dict):
        return []
    accessions = recent.get("accessionNumber") or []
    keys = (
        "accessionNumber",
        "filingDate",
        "reportDate",
        "form",
        "primaryDocument",
    )
    return [
        {key: (recent.get(key) or [None] * len(accessions))[index] for key in keys}
        for index in range(len(accessions))
    ]


def ingest_submissions_payload(session: Session, company: Company, payload: dict[str, Any]) -> int:
    company.sic = str(payload.get("sic")) if payload.get("sic") else company.sic
    company.fiscal_year_end = payload.get("fiscalYearEnd") or company.fiscal_year_end
    tickers = payload.get("tickers") or []
    exchanges = payload.get("exchanges") or []
    if tickers:
        company.is_active = True
        session.execute(
            update(Security).where(Security.company_id == company.id).values(is_active=False)
        )
        for index, ticker in enumerate(tickers):
            exchange = exchanges[index] if index < len(exchanges) else None
            security = session.scalar(
                select(Security).where(
                    Security.company_id == company.id,
                    Security.ticker == str(ticker).upper(),
                    Security.exchange == exchange,
                )
            )
            if security:
                security.is_active = True
            else:
                session.add(
                    Security(
                        company_id=company.id,
                        ticker=str(ticker).upper(),
                        exchange=exchange,
                        is_active=True,
                    )
                )
    filing_rows: list[dict[str, Any]] = []
    for row in _columnar_rows(payload):
        accession = row.get("accessionNumber")
        filed = _parse_date(row.get("filingDate"))
        form = row.get("form")
        if not accession or not filed or not form:
            continue
        filing_rows.append(
            {
                "company_id": company.id,
                "accession": accession,
                "form": form,
                "filed": filed,
                "report_date": _parse_date(row.get("reportDate")),
                "primary_document": row.get("primaryDocument") or None,
                "is_amendment": form.endswith("/A"),
            }
        )

    if session.bind and session.bind.dialect.name == "postgresql":
        for start in range(0, len(filing_rows), 2_000):
            statement = postgresql_insert(Filing).values(filing_rows[start : start + 2_000])
            session.execute(
                statement.on_conflict_do_update(
                    index_elements=[Filing.company_id, Filing.accession],
                    set_={
                        "form": statement.excluded.form,
                        "filed": statement.excluded.filed,
                        "report_date": statement.excluded.report_date,
                        "primary_document": statement.excluded.primary_document,
                        "is_amendment": statement.excluded.is_amendment,
                    },
                )
            )
    else:
        existing = {
            filing.accession: filing
            for filing in session.scalars(select(Filing).where(Filing.company_id == company.id))
        }
        for values in filing_rows:
            filing = existing.get(values["accession"])
            if filing:
                for key, value in values.items():
                    if key not in {"company_id", "accession"}:
                        setattr(filing, key, value)
            else:
                session.add(Filing(**values))
    session.commit()
    return len(filing_rows)


def _update_run(session: Session, run_id: str, **values: Any) -> None:
    session.execute(update(SyncRun).where(SyncRun.id == run_id).values(**values))
    session.commit()


def _validate_zip(path: Path) -> None:
    if not zipfile.is_zipfile(path):
        raise RuntimeError(f"Invalid ZIP archive: {path}")
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if not entries:
            raise RuntimeError(f"Empty ZIP archive: {path}")
        # Entry CRCs are verified as each JSON file is streamed during ingestion.
        if any(item.file_size < 0 or item.compress_size < 0 for item in entries):
            raise RuntimeError(f"Invalid ZIP central directory: {path}")


def _download_if_changed(
    client: SecClient,
    key: str,
    url: str,
    path: Path,
    manifest: dict[str, dict[str, Any]],
) -> DownloadMetadata:
    headers = client.head(url)
    etag = headers.get("ETag")
    last_modified = headers.get("Last-Modified")
    previous = manifest.get(key) or {}
    if path.exists() and (
        (etag and previous.get("etag") == etag)
        or (last_modified and previous.get("last_modified") == last_modified)
    ):
        return DownloadMetadata(path, etag, last_modified, path.stat().st_size)
    metadata = client.download(url, path)
    manifest[key] = {
        "etag": metadata.etag or etag,
        "last_modified": metadata.last_modified or last_modified,
        "content_length": metadata.content_length,
        "downloaded_at": datetime.now(UTC).isoformat(),
    }
    manifest_path = path.parent / "source_manifest.json"
    partial_manifest = manifest_path.with_suffix(".json.partial")
    partial_manifest.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    partial_manifest.replace(manifest_path)
    return metadata


def _require_disk_space(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(path).free
    if free < MIN_FREE_BYTES:
        raise RuntimeError(
            "SEC bulk import requires at least 60 GiB free; "
            f"only {free / 1024**3:.1f} GiB available."
        )


def run_company_sync(run_id: str, cik: str, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    with SessionLocal() as session:
        _update_run(
            session,
            run_id,
            status="running",
            started_at=datetime.now(UTC),
            progress_current=0,
            progress_total=2,
            message="下載 Company Facts",
        )
    with SecClient(settings) as client:
        facts_payload = client.company_facts(cik)
        submissions_payload = client.submissions(cik)
    with SessionLocal() as session:
        company = ingest_companyfacts_payload(session, facts_payload, run_id=run_id)
        _update_run(session, run_id, progress_current=1, message="匯入申報資料")
        ingest_submissions_payload(session, company, submissions_payload)
        _update_run(
            session,
            run_id,
            status="completed",
            progress_current=2,
            completed_at=datetime.now(UTC),
            message="單一公司同步完成",
        )


def run_bulk_sync(
    run_id: str,
    settings: Settings | None = None,
    ticker_filter: set[str] | frozenset[str] | None = None,
) -> None:
    settings = settings or get_settings()
    _require_disk_space(settings.data_dir)
    with SessionLocal() as session:
        current_run = session.get(SyncRun, run_id)
        previous_progress = current_run.progress_current if current_run else 0
        previous_etag = current_run.source_etag if current_run else None
        _update_run(
            session,
            run_id,
            status="running",
            started_at=datetime.now(UTC),
            message="下載 SEC 清單",
        )
    with SecClient(settings) as client:
        exchange = client.get_json(URLS["tickers"])
        funds = client.get_json(URLS["funds"])
        manifest_path = settings.data_dir / "source_manifest.json"
        manifest = (
            json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
        )
        companyfacts_meta = _download_if_changed(
            client,
            "companyfacts",
            URLS["companyfacts"],
            settings.data_dir / "companyfacts.zip",
            manifest,
        )
        _download_if_changed(
            client,
            "submissions",
            URLS["submissions"],
            settings.data_dir / "submissions.zip",
            manifest,
        )
    _validate_zip(settings.data_dir / "companyfacts.zip")
    _validate_zip(settings.data_dir / "submissions.zip")

    with SessionLocal() as session:
        sync_metric_registry(session)
        eligible_ciks = upsert_universe(session, exchange, funds, ticker_filter)
        scope = f"市值前 100（{TOP100_AS_OF}）" if ticker_filter is not None else "全市場"
        resume_companyfacts = (
            previous_progress >= len(eligible_ciks)
            and previous_etag is not None
            and previous_etag == companyfacts_meta.etag
        )
        _update_run(
            session,
            run_id,
            progress_current=len(eligible_ciks) if resume_companyfacts else 0,
            progress_total=len(eligible_ciks) * 2,
            source_etag=companyfacts_meta.etag,
            message=(
                f"從 checkpoint 恢復 {scope} Submissions"
                if resume_companyfacts
                else f"匯入 {scope} Company Facts"
            ),
        )

    supported_ciks: set[str] = set()
    processed = 0
    with SessionLocal() as session:
        concept_id_cache = {
            (taxonomy, name): concept_id
            for concept_id, taxonomy, name in session.execute(
                select(Concept.id, Concept.taxonomy, Concept.name)
            )
        }
    with zipfile.ZipFile(settings.data_dir / "companyfacts.zip") as archive:
        companyfact_names = [
            name
            for name in archive.namelist()
            if (match := CIK_PATTERN.search(name)) and match.group(1) in eligible_ciks
        ]
        if resume_companyfacts:
            with SessionLocal() as session:
                supported_ciks = set(
                    session.scalars(
                        select(Company.cik).where(
                            Company.cik.in_(eligible_ciks),
                            Company.supported.is_(True),
                        )
                    )
                )
            processed = len(companyfact_names)
        else:
            for name in companyfact_names:
                match = CIK_PATTERN.search(name)
                if match is None:
                    continue
                payload = json.loads(archive.read(name))
                with SessionLocal() as session:
                    company = ingest_companyfacts_payload(
                        session,
                        payload,
                        run_id=run_id,
                        concept_id_cache=concept_id_cache,
                    )
                    if company.supported:
                        supported_ciks.add(company.cik)
                    processed += 1
                    if processed % 10 == 0:
                        _update_run(
                            session,
                            run_id,
                            progress_current=processed,
                            message=f"已處理 {processed:,} 家 Company Facts",
                        )

    with zipfile.ZipFile(settings.data_dir / "submissions.zip") as archive:
        submission_names = [
            name
            for name in archive.namelist()
            if (match := CIK_PATTERN.search(name)) and match.group(1) in supported_ciks
        ]
        with SessionLocal() as session:
            _update_run(
                session,
                run_id,
                progress_current=processed,
                progress_total=processed + len(submission_names),
                message=f"匯入 {scope} Submissions",
            )
        for name in submission_names:
            match = CIK_PATTERN.search(name)
            if match is None:
                continue
            payload = json.loads(archive.read(name))
            with SessionLocal() as session:
                company = session.scalar(select(Company).where(Company.cik == match.group(1)))
                if company:
                    ingest_submissions_payload(session, company, payload)
                    processed += 1
                    if processed % 10 == 0:
                        _update_run(
                            session,
                            run_id,
                            progress_current=processed,
                            message=f"已處理 {processed:,} 個資料檔",
                        )
    with SessionLocal() as session:
        _update_run(
            session,
            run_id,
            status="completed",
            progress_current=processed,
            progress_total=processed,
            completed_at=datetime.now(UTC),
            message=f"{scope}同步完成，共 {len(supported_ciks):,} 家 US-GAAP 公司",
        )


def run_top100_sync(run_id: str, settings: Settings | None = None) -> None:
    run_bulk_sync(run_id, settings=settings, ticker_filter=TOP100_TICKERS)
