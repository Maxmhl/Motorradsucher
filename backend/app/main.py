"""FastAPI-Anwendung: API, WebSocket, Scheduler und ausgeliefertes Frontend."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import scheduler as scheduler_mod
from app.api import routes_listings, routes_models, routes_runs, routes_settings, ws
from app.config import settings
from app.db import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
)
log = logging.getLogger("motorradsucher")

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend" / "dist"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await init_db()
    scheduler_mod.start()
    schedule = await scheduler_mod.apply_schedule()
    log.info("Datenbank bereit: %s", settings.sqlalchemy_url)
    log.info("Zeitplan: %s", schedule)
    yield
    scheduler_mod.shutdown()


app = FastAPI(
    title="Motorrad-Sucher",
    version="0.1.0",
    description="Automatisierte Motorrad-Suche mit lokaler KI-Vorfilterung über Ollama",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(routes_runs.router)
app.include_router(routes_listings.router)
app.include_router(routes_settings.router)
app.include_router(routes_models.router)
app.include_router(ws.router)


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "version": app.version}


# Gebautes Frontend ausliefern (Produktion). Im Dev-Modus laeuft stattdessen Vite.
if FRONTEND_DIR.exists():
    app.mount(
        "/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="assets"
    )

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str) -> FileResponse:
        candidate = FRONTEND_DIR / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIR / "index.html")
