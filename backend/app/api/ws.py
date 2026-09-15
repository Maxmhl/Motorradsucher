"""WebSocket fuer den Live-Fortschritt im Dashboard."""

from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.events import bus
from app.pipeline.runner import runner

log = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        await websocket.send_json({"type": "hello", "payload": runner.status()})
        async for event in bus.subscribe():
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001 - abgebrochene Verbindungen sind normal
        log.debug("WebSocket beendet", exc_info=True)
