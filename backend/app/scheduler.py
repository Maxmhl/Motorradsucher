"""Cron-artiger Scheduler fuer automatische Runs."""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings
from app.db import session_scope
from app.pipeline.runner import RunnerBusyError, runner
from app.settings_store import get_all

log = logging.getLogger(__name__)

JOB_ID = "scheduled_run"

scheduler = AsyncIOScheduler(timezone=settings.scheduler_timezone)


async def _scheduled_run() -> None:
    try:
        run_id = await runner.start(trigger="schedule")
        log.info("Geplanter Run %s gestartet", run_id)
    except RunnerBusyError:
        log.warning("Geplanter Run übersprungen - es läuft bereits ein Run")


async def apply_schedule() -> dict[str, str | bool | None]:
    """Liest die Einstellungen und richtet den Cron-Job ein bzw. entfernt ihn."""
    async with session_scope() as session:
        values = await get_all(session)

    enabled = bool(values.get("schedule_enabled"))
    expression = str(values.get("schedule_cron") or "").strip()

    if scheduler.get_job(JOB_ID):
        scheduler.remove_job(JOB_ID)

    if not enabled or not expression:
        return {"enabled": False, "cron": expression or None, "next_run": None, "error": None}

    try:
        trigger = CronTrigger.from_crontab(expression, timezone=settings.scheduler_timezone)
    except ValueError as exc:
        log.error("Ungültiger Cron-Ausdruck %r: %s", expression, exc)
        return {"enabled": False, "cron": expression, "next_run": None, "error": str(exc)}

    job = scheduler.add_job(_scheduled_run, trigger=trigger, id=JOB_ID, replace_existing=True)
    return {
        "enabled": True,
        "cron": expression,
        "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
        "error": None,
    }


def describe() -> dict[str, str | bool | None]:
    job = scheduler.get_job(JOB_ID)
    return {
        "running": scheduler.running,
        "scheduled": job is not None,
        "next_run": job.next_run_time.isoformat() if job and job.next_run_time else None,
        "timezone": settings.scheduler_timezone,
    }


def start() -> None:
    if not scheduler.running:
        scheduler.start()


def shutdown() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
