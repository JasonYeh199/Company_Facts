from __future__ import annotations

import uuid

import typer

from .db import Base, SessionLocal, engine
from .ingestion import run_bulk_sync, run_company_sync, run_top100_sync, sync_metric_registry
from .models import SyncRun

app = typer.Typer(help="SEC Company Facts database utilities")


@app.command("init-db")
def init_db() -> None:
    """Create a development schema and seed the metric registry."""
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        sync_metric_registry(session)
        session.commit()
    typer.echo("Database initialized.")


@app.command("sync")
def sync(
    kind: str = typer.Option("bulk", help="bulk, top100, or company"),
    cik: str | None = typer.Option(None, help="CIK for company sync"),
) -> None:
    """Run a sync immediately in the current process."""
    if kind not in {"bulk", "top100", "company"}:
        raise typer.BadParameter("kind must be bulk, top100, or company")
    if kind == "company" and not cik:
        raise typer.BadParameter("--cik is required for company sync")
    normalized_cik = str(cik).zfill(10) if cik else None
    run_id = str(uuid.uuid4())
    with SessionLocal() as session:
        session.add(
            SyncRun(
                id=run_id,
                kind=kind,
                cik=normalized_cik,
                status="pending",
                progress_current=0,
            )
        )
        session.commit()
    if kind == "bulk":
        run_bulk_sync(run_id)
    elif kind == "top100":
        run_top100_sync(run_id)
    else:
        run_company_sync(run_id, normalized_cik or "")
    typer.echo(f"Sync completed: {run_id}")


if __name__ == "__main__":
    app()
