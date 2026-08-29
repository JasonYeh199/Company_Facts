from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select

from .config import get_settings
from .db import SessionLocal
from .ingestion import run_bulk_sync, run_company_sync, run_top100_sync
from .models import SyncRun
from .price_sync import run_price_sync

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def enqueue_scheduled_bulk() -> None:
    now_et = datetime.now(ZoneInfo("America/New_York"))
    if now_et.hour < 4:
        return
    with SessionLocal() as session:
        active = session.scalar(
            select(SyncRun.id).where(
                SyncRun.kind.in_(("bulk", "top100")),
                SyncRun.status.in_(("pending", "running")),
            )
        )
        if active:
            return
        latest = session.scalar(
            select(SyncRun)
            .where(SyncRun.kind.in_(("bulk", "top100")), SyncRun.status == "completed")
            .order_by(SyncRun.completed_at.desc())
            .limit(1)
        )
        # First bootstrap is deliberately user-triggered from the setup page.
        if latest is None or latest.completed_at is None:
            return
        completed_et = latest.completed_at.astimezone(ZoneInfo("America/New_York"))
        if completed_et.date() >= now_et.date():
            return
        session.add(
            SyncRun(
                id=str(uuid.uuid4()),
                kind=latest.kind,
                status="pending",
                progress_current=0,
                message="每日排程同步",
            )
        )
        session.commit()


def enqueue_scheduled_prices() -> None:
    settings = get_settings()
    if not settings.tiingo_is_configured:
        return
    now_et = datetime.now(ZoneInfo("America/New_York"))
    if now_et.weekday() == 5 or (now_et.hour, now_et.minute) < (20, 30):
        return
    with SessionLocal() as session:
        active = session.scalar(
            select(SyncRun.id).where(
                SyncRun.kind.in_(("prices", "price_company")),
                SyncRun.status.in_(("pending", "running")),
            )
        )
        if active:
            return
        latest = session.scalar(
            select(SyncRun)
            .where(
                SyncRun.kind == "prices",
                SyncRun.status.in_(("completed", "completed_with_errors")),
            )
            .order_by(SyncRun.completed_at.desc())
            .limit(1)
        )
        if (
            latest is not None
            and latest.completed_at is not None
            and latest.completed_at.astimezone(ZoneInfo("America/New_York")).date()
            >= now_et.date()
        ):
            return
        session.add(
            SyncRun(
                id=str(uuid.uuid4()),
                kind="prices",
                status="pending",
                progress_current=0,
                message="排程 Tiingo Daily EOD 更新",
            )
        )
        session.commit()


def claim_next_run() -> tuple[str, str, str | None] | None:
    with SessionLocal() as session:
        query = (
            select(SyncRun).where(SyncRun.status == "pending").order_by(SyncRun.created_at).limit(1)
        )
        if session.bind and session.bind.dialect.name == "postgresql":
            query = query.with_for_update(skip_locked=True)
        run = session.scalar(query)
        if run is None:
            return None
        run.status = "running"
        run.started_at = datetime.now(UTC)
        run.message = "worker 已接手"
        session.commit()
        return run.id, run.kind, run.cik


def fail_run(run_id: str, exc: Exception) -> None:
    with SessionLocal() as session:
        run = session.get(SyncRun, run_id)
        if run:
            run.status = "failed"
            run.error = f"{type(exc).__name__}: {exc}"
            run.message = "同步失敗"
            run.completed_at = datetime.now(UTC)
            session.commit()


def process_once() -> bool:
    claimed = claim_next_run()
    if claimed is None:
        return False
    run_id, kind, cik = claimed
    logger.info("Processing %s sync %s", kind, run_id)
    try:
        if kind == "bulk":
            run_bulk_sync(run_id)
        elif kind == "top100":
            run_top100_sync(run_id)
        elif kind == "company" and cik:
            run_company_sync(run_id, cik)
        elif kind == "prices":
            run_price_sync(run_id)
        elif kind == "price_company" and cik:
            run_price_sync(run_id, cik=cik)
        else:
            raise ValueError(f"Unsupported sync job: kind={kind!r}, cik={cik!r}")
    except Exception as exc:
        logger.exception("Sync %s failed", run_id)
        fail_run(run_id, exc)
    return True


def main() -> None:
    settings = get_settings()
    logger.info("Company Facts worker started")
    while True:
        enqueue_scheduled_bulk()
        enqueue_scheduled_prices()
        if not process_once():
            time.sleep(settings.sync_poll_seconds)


if __name__ == "__main__":
    main()
