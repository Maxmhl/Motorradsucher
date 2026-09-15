"""Einstellungen: Modellauswahl, Suchkriterien, Freitext-Kriterien, Zeitplan."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app import scheduler as scheduler_mod
from app.db import get_session
from app.schemas import SettingsIn, SiteOut
from app.scrapers.config import get_sites, reload_sites
from app.settings_store import get_all, set_many

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("")
async def read_settings(session: AsyncSession = Depends(get_session)) -> dict:
    return await get_all(session)


@router.put("")
async def update_settings(
    payload: SettingsIn, session: AsyncSession = Depends(get_session)
) -> dict:
    values = payload.model_dump(exclude_none=True)
    updated = await set_many(session, values)
    schedule = None
    if "schedule_enabled" in values or "schedule_cron" in values:
        schedule = await scheduler_mod.apply_schedule()
    return {"settings": updated, "schedule": schedule}


@router.get("/sites", response_model=list[SiteOut])
async def list_sites() -> list[SiteOut]:
    return [
        SiteOut(
            key=cfg.key,
            name=cfg.name,
            enabled=cfg.enabled,
            fetcher=cfg.fetcher,
            search_url_template=cfg.search_url_template,
        )
        for cfg in get_sites().values()
    ]


@router.post("/sites/reload", response_model=list[SiteOut])
async def reload_site_config() -> list[SiteOut]:
    """Laedt sites.yaml neu - nach einer Selektor-Anpassung ohne Neustart."""
    return [
        SiteOut(
            key=cfg.key,
            name=cfg.name,
            enabled=cfg.enabled,
            fetcher=cfg.fetcher,
            search_url_template=cfg.search_url_template,
        )
        for cfg in reload_sites().values()
    ]
