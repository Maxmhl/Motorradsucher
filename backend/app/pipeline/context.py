"""Laufzeit-Kontext eines Runs: Logging in die DB, Fortschritt per WebSocket."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from app.db import session_scope
from app.events import bus
from app.models import LogEntry

log = logging.getLogger(__name__)

STAGES = [
    ("scrape", "Scraping"),
    ("text", "Text-Analyse"),
    ("vision", "Bild-Analyse"),
    ("classify", "Klassifizierung"),
    ("cleanup", "Bilder löschen"),
    ("rank", "Ranking"),
]


class RunCancelled(Exception):
    """Wird geworfen, wenn der Nutzer den Run im UI abbricht."""


@dataclass
class RunContext:
    run_id: int
    settings: dict[str, Any]
    stats: dict[str, Any] = field(default_factory=dict)
    current_stage: str = "scrape"
    _cancel: asyncio.Event = field(default_factory=asyncio.Event)

    # -- Abbruch ----------------------------------------------------------
    def cancel(self) -> None:
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise RunCancelled

    # -- Fortschritt ------------------------------------------------------
    def stage(self, key: str) -> dict[str, Any]:
        return self.stats.setdefault(key, {"done": 0, "total": 0, "state": "pending"})

    async def start_stage(self, key: str, total: int = 0) -> None:
        self.current_stage = key
        entry = self.stage(key)
        entry.update({"state": "running", "total": total, "done": 0})
        await self.publish()

    async def advance(self, key: str, count: int = 1, **extra: Any) -> None:
        entry = self.stage(key)
        entry["done"] = entry.get("done", 0) + count
        for name, value in extra.items():
            entry[name] = entry.get(name, 0) + value
        await self.publish()

    async def finish_stage(self, key: str, **extra: Any) -> None:
        entry = self.stage(key)
        entry["state"] = "done"
        entry.update(extra)
        await self.publish()

    async def publish(self) -> None:
        await bus.publish(
            "run_progress",
            {"run_id": self.run_id, "stage": self.current_stage, "stats": self.stats},
        )

    # -- Logging ----------------------------------------------------------
    async def log(self, message: str, level: str = "info", stage: str | None = None) -> None:
        stage = stage or self.current_stage
        log.log(
            {"debug": logging.DEBUG, "warning": logging.WARNING, "error": logging.ERROR}.get(
                level, logging.INFO
            ),
            "[run %s/%s] %s",
            self.run_id,
            stage,
            message,
        )
        async with session_scope() as session:
            session.add(
                LogEntry(run_id=self.run_id, level=level, stage=stage, message=message)
            )
        await bus.publish(
            "log",
            {"run_id": self.run_id, "level": level, "stage": stage, "message": message},
        )
