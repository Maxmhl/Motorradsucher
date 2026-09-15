"""Modell-Auswahl: liest die installierten Ollama-Modelle per /api/tags."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.ollama import OllamaClient, OllamaError
from app.schemas import ModelOut, ModelsResponse
from app.settings_store import get_all

router = APIRouter(prefix="/api/models", tags=["models"])


def _endpoints(settings_values: dict) -> dict[str, str]:
    """Eindeutige Ollama-URLs mit den Stages, die sie bedienen.

    Beruecksichtigt die im UI hinterlegten Adressen (Tabelle `settings`) vor
    dem .env-Fallback - siehe app.ollama.client_for.
    """
    from app.ollama import client_for

    mapping: dict[str, list[str]] = {}
    for stage in ("text", "vision", "interpretation", "ranking"):
        url = client_for(stage, settings_values).base_url
        mapping.setdefault(url, []).append(stage)
    return {url: ", ".join(stages) for url, stages in mapping.items()}


@router.get("", response_model=ModelsResponse)
async def list_models(session: AsyncSession = Depends(get_session)) -> ModelsResponse:
    endpoints: list[dict] = []
    seen: dict[str, ModelOut] = {}
    errors: list[str] = []

    settings_values = await get_all(session)
    for url, stages in _endpoints(settings_values).items():
        client = OllamaClient(url)
        try:
            models = await client.list_models()
        except OllamaError as exc:
            errors.append(str(exc))
            endpoints.append({"url": url, "stages": stages, "reachable": False, "count": 0})
            continue
        endpoints.append(
            {"url": url, "stages": stages, "reachable": True, "count": len(models)}
        )
        for entry in models:
            seen.setdefault(entry["name"], ModelOut(**entry))

    return ModelsResponse(
        endpoints=endpoints,
        models=sorted(seen.values(), key=lambda m: m.name),
        error="; ".join(errors) or None,
    )


@router.post("/test")
async def test_model(payload: dict, session: AsyncSession = Depends(get_session)) -> dict:
    """Testcall gegen ein Modell - prueft Erreichbarkeit und Antwortformat."""
    model = (payload.get("model") or "").strip()
    stage = payload.get("stage") or "text"
    if not model:
        return {"ok": False, "error": "Kein Modell angegeben"}
    from app.ollama import client_for

    settings_values = await get_all(session)
    client = client_for(stage, settings_values)
    try:
        response = await client.generate_text(
            model,
            "Antworte mit genau einem Wort: bereit",
            temperature=0.0,
        )
    except OllamaError as exc:
        return {"ok": False, "error": str(exc), "url": client.base_url}
    return {"ok": True, "response": response[:200], "url": client.base_url}
