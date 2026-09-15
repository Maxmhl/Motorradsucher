"""Runs starten/abbrechen, Dashboard-Kennzahlen, Logs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import scheduler as scheduler_mod
from app.config import settings
from app.db import get_session
from app.models import FinalClass, Listing, ListingStatus, LogEntry, Run
from app.ollama import OllamaClient
from app.pipeline.runner import RunnerBusyError, runner
from app.schemas import DashboardOut, LogOut, RunOut

router = APIRouter(prefix="/api", tags=["runs"])


@router.post("/runs", response_model=RunOut, status_code=201)
async def start_run(session: AsyncSession = Depends(get_session)) -> Run:
    try:
        run_id = await runner.start(trigger="manual")
    except RunnerBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    run = await session.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=500, detail="Run konnte nicht angelegt werden")
    return run


@router.post("/runs/cancel")
async def cancel_run() -> dict:
    return {"cancelled": runner.cancel(), "run_id": runner.current_run_id}


@router.get("/runs", response_model=list[RunOut])
async def list_runs(
    limit: int = Query(20, ge=1, le=200), session: AsyncSession = Depends(get_session)
) -> list[Run]:
    rows = await session.execute(select(Run).order_by(Run.id.desc()).limit(limit))
    return list(rows.scalars().all())


@router.get("/runs/{run_id}", response_model=RunOut)
async def get_run(run_id: int, session: AsyncSession = Depends(get_session)) -> Run:
    run = await session.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run nicht gefunden")
    return run


@router.get("/logs", response_model=list[LogOut])
async def list_logs(
    run_id: int | None = None,
    level: str | None = None,
    limit: int = Query(200, ge=1, le=2000),
    session: AsyncSession = Depends(get_session),
) -> list[LogEntry]:
    query = select(LogEntry).order_by(LogEntry.id.desc()).limit(limit)
    if run_id is not None:
        query = query.where(LogEntry.run_id == run_id)
    if level:
        query = query.where(LogEntry.level == level)
    rows = await session.execute(query)
    return list(reversed(rows.scalars().all()))


@router.get("/dashboard", response_model=DashboardOut)
async def dashboard(session: AsyncSession = Depends(get_session)) -> DashboardOut:
    latest = (
        await session.execute(select(Run).order_by(Run.id.desc()).limit(1))
    ).scalar_one_or_none()

    total = (await session.execute(select(func.count(Listing.id)))).scalar_one()
    counts = {"gesamt": total}
    for status in ListingStatus:
        counts[status.value] = (
            await session.execute(
                select(func.count(Listing.id)).where(Listing.status == status)
            )
        ).scalar_one()
    for final in FinalClass:
        counts[final.value] = (
            await session.execute(
                select(func.count(Listing.id)).where(Listing.final_class == final)
            )
        ).scalar_one()

    endpoints: dict[str, list[str]] = {}
    for stage in ("text", "vision", "interpretation", "ranking"):
        endpoints.setdefault(settings.ollama_url_for(stage), []).append(stage)
    ollama = []
    for url, stages in endpoints.items():
        health = await OllamaClient(url).health()
        ollama.append({**health, "stages": stages})

    return DashboardOut(
        runner=runner.status(),
        scheduler=scheduler_mod.describe(),
        latest_run=RunOut.model_validate(latest) if latest else None,
        counts=counts,
        ollama=ollama,
    )
