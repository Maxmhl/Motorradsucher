"""Anwendungs-Einstellungen (DB-Tabelle `settings`) mit Defaults aus dem Projektplan."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Setting

# Defaults entsprechen der Ausgangslage aus Abschnitt 1 des Plans.
DEFAULTS: dict[str, Any] = {
    # --- Modellauswahl je Pipeline-Stage (leer = Stage wird uebersprungen) ---
    "text_model": "",
    "vision_model": "",
    "interpretation_model": "",
    "ranking_model": "",
    # --- Suchkriterien ---
    "criteria": {
        "budget_max": 5000,
        "year_min": 2018,
        "km_max": 30000,
        "models": [
            "Kawasaki Z650",
            "Yamaha MT-07",
            "Honda CB650R",
            "Honda CB500F",
            "Suzuki SV650",
        ],
        "zip_code": "",
        "radius_km": 200,
    },
    # --- Freitext-Kriterien fuer die KI-Stufen ---
    "text_exclusions": (
        "Unfall, Unfallschaden, Sturz, gestürzt, Rahmenschaden, Motorschaden, "
        "Getriebeschaden, Bastlerfahrzeug, Teileträger, Export, defekt, "
        "nicht fahrbereit, ohne Papiere"
    ),
    "optical_criteria": (
        "Bevorzugt blauer Rahmen mit blauen Felgen. "
        "Keine auffälligen Kratzer an Tank oder Verkleidung, keine Schleifspuren "
        "an Lenkerenden, Hebeln oder Fußrasten, keine ausgeblichenen Teile."
    ),
    # --- Ollama-Verbindung (leer = Fallback auf .env/OLLAMA_BASE_URL*) ---
    "ollama_base_url": "",
    "ollama_base_url_text": "",
    "ollama_base_url_vision": "",
    # --- Verhalten ---
    "top_n_rejected": 3,  # Top 3 je Reject-Klasse im UI (Stufe 6)
    "keep_thumbnail": True,  # ein Vorschaubild je Inserat dauerhaft behalten
    "max_listings_per_run": 200,
    # --- Scheduler ---
    "schedule_enabled": False,
    "schedule_cron": "0 7 * * *",
}


async def get_all(session: AsyncSession) -> dict[str, Any]:
    rows = (await session.execute(select(Setting))).scalars().all()
    stored = {r.key: r.value for r in rows}
    merged = dict(DEFAULTS)
    for key, value in stored.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


async def get(session: AsyncSession, key: str, default: Any = None) -> Any:
    return (await get_all(session)).get(key, default if default is not None else DEFAULTS.get(key))


async def set_many(session: AsyncSession, values: dict[str, Any]) -> dict[str, Any]:
    for key, value in values.items():
        row = await session.get(Setting, key)
        if row is None:
            session.add(Setting(key=key, value=value))
        else:
            row.value = value
    await session.commit()
    return await get_all(session)
