"""In-Memory-Event-Bus fuer den Live-Fortschritt im Dashboard (WebSocket)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

log = logging.getLogger(__name__)

QUEUE_SIZE = 200


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._last_state: dict[str, Any] | None = None

    async def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        event = {
            "type": event_type,
            "ts": datetime.now(UTC).isoformat(),
            "payload": payload,
        }
        if event_type in ("run_progress", "run_started", "run_finished"):
            self._last_state = event
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # Langsame Clients duerfen die Pipeline nicht ausbremsen.
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
                with contextlib.suppress(asyncio.QueueFull):
                    queue.put_nowait(event)

    @property
    def last_state(self) -> dict[str, Any] | None:
        return self._last_state

    async def subscribe(self) -> AsyncIterator[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=QUEUE_SIZE)
        self._subscribers.add(queue)
        try:
            if self._last_state:
                yield self._last_state
            while True:
                yield await queue.get()
        finally:
            self._subscribers.discard(queue)


bus = EventBus()
