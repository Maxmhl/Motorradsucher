"""Asynchroner Pipeline-Runner - fuehrt die sechs Stufen eines Runs aus.

Single-Node: ein Run zur Zeit, als asyncio.Task im laufenden FastAPI-Prozess.
Kein Redis/Celery noetig.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.db import session_scope
from app.events import bus
from app.models import FinalClass, Listing, ListingStatus, Run, RunStatus
from app.pipeline import (
    stage_classify,
    stage_cleanup,
    stage_rank,
    stage_scrape,
    stage_text,
    stage_vision,
)
from app.pipeline.context import RunCancelled, RunContext
from app.settings_store import get_all

log = logging.getLogger(__name__)


class RunnerBusyError(RuntimeError):
    pass


class PipelineRunner:
    """Haelt den aktuell laufenden Run und stellt Start/Abbruch bereit."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._ctx: RunContext | None = None

    @property
    def busy(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def current_run_id(self) -> int | None:
        return self._ctx.run_id if self._ctx and self.busy else None

    def status(self) -> dict[str, Any]:
        return {
            "busy": self.busy,
            "run_id": self.current_run_id,
            "stage": self._ctx.current_stage if self._ctx and self.busy else None,
            "stats": self._ctx.stats if self._ctx and self.busy else {},
        }

    async def start(self, trigger: str = "manual") -> int:
        if self.busy:
            raise RunnerBusyError("Es läuft bereits ein Run")

        async with session_scope() as session:
            settings_snapshot = await get_all(session)
            run = Run(trigger=trigger, status=RunStatus.running, stage_stats={})
            session.add(run)
            await session.flush()
            run_id = run.id

        ctx = RunContext(run_id=run_id, settings=settings_snapshot)
        self._ctx = ctx
        self._task = asyncio.create_task(self._execute(ctx), name=f"run-{run_id}")
        await bus.publish("run_started", {"run_id": run_id, "trigger": trigger})
        return run_id

    def cancel(self) -> bool:
        if self._ctx and self.busy:
            self._ctx.cancel()
            return True
        return False

    async def _execute(self, ctx: RunContext) -> None:
        status = RunStatus.finished
        error: str | None = None
        try:
            await ctx.log(f"Run {ctx.run_id} gestartet")

            # Stufe 1
            new_ids = await stage_scrape.run_stage(ctx)

            # Inserate, die aus frueheren Runs noch unfertig sind, mitnehmen.
            pending = await _pending_listing_ids()
            listing_ids = list(dict.fromkeys(new_ids + pending))
            if pending:
                await ctx.log(f"{len(pending)} unfertige Inserate aus früheren Runs übernommen")

            # Stufe 2
            text_ok = await stage_text.run_stage(ctx, listing_ids)
            # Stufe 3
            await stage_vision.run_stage(ctx, text_ok)
            # Stufe 4
            await stage_classify.run_stage(ctx, listing_ids)
            # Stufe 5
            await stage_cleanup.run_stage(ctx, listing_ids)
            # Stufe 6 - alle Inserate je Klasse neu ranken, nicht nur die neuen,
            # damit die Reihenfolge im UI klassenweit stimmt.
            await stage_rank.run_stage(ctx, await _all_by_class())

        except RunCancelled:
            status = RunStatus.cancelled
            await ctx.log("Run vom Nutzer abgebrochen", level="warning")
        except Exception as exc:  # noqa: BLE001
            status = RunStatus.failed
            error = str(exc)
            log.exception("Run %s fehlgeschlagen", ctx.run_id)
            await ctx.log(f"Run fehlgeschlagen: {exc}", level="error")
        finally:
            async with session_scope() as session:
                run = await session.get(Run, ctx.run_id)
                if run:
                    run.status = status
                    run.finished_at = datetime.now(UTC)
                    run.stage_stats = ctx.stats
                    run.error_message = error
            await bus.publish(
                "run_finished",
                {"run_id": ctx.run_id, "status": status.value, "stats": ctx.stats},
            )
            await ctx.log(f"Run {ctx.run_id} beendet: {status.value}")


async def _pending_listing_ids(limit: int = 500) -> list[int]:
    """Inserate, die noch nicht final klassifiziert sind."""
    async with session_scope() as session:
        rows = await session.execute(
            select(Listing.id)
            .where(
                Listing.final_class.is_(None),
                Listing.status.in_([ListingStatus.new, ListingStatus.text_ok]),
            )
            .limit(limit)
        )
        return list(rows.scalars().all())


async def _all_by_class() -> dict[str, list[int]]:
    async with session_scope() as session:
        rows = await session.execute(
            select(Listing.id, Listing.final_class).where(Listing.final_class.is_not(None))
        )
        buckets: dict[str, list[int]] = {c.value: [] for c in FinalClass}
        for listing_id, final_class in rows.all():
            key = final_class.value if isinstance(final_class, FinalClass) else str(final_class)
            buckets.setdefault(key, []).append(listing_id)
        return buckets


runner = PipelineRunner()
