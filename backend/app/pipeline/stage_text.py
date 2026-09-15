"""Stufe 2 - Text-Analyse mit einem frei waehlbaren Ollama-Textmodell.

Abgelehnte Inserate werden markiert, nicht geloescht - sie bleiben fuer die
spaetere manuelle Durchsicht sichtbar.
"""

from __future__ import annotations

import asyncio

from app.config import settings as app_settings
from app.db import session_scope
from app.models import Listing, ListingStatus
from app.ollama import OllamaError, client_for
from app.pipeline.context import RunContext
from app.pipeline.prompts import TEXT_SYSTEM, text_prompt


def _as_dict(listing: Listing) -> dict:
    return {
        "title": listing.title,
        "price": listing.price,
        "year": listing.year,
        "km": listing.km,
        "location": listing.location,
        "description": listing.description,
    }


async def run_stage(ctx: RunContext, listing_ids: list[int]) -> list[int]:
    """Bewertet alle uebergebenen Inserate. Gibt die IDs mit text_ok zurueck."""
    model = (ctx.settings.get("text_model") or "").strip()
    exclusions = ctx.settings.get("text_exclusions") or ""
    criteria = ctx.settings.get("criteria") or {}

    await ctx.start_stage("text", total=len(listing_ids))
    if not listing_ids:
        await ctx.finish_stage("text", ok=0, rejected=0, errors=0)
        return []
    if not model:
        # Ohne gewaehltes Modell wird nicht geraten - alle kommen durch,
        # damit die Pipeline trotzdem ein Ergebnis liefert.
        await ctx.log(
            "Kein Textmodell gewählt - Stufe 2 übersprungen, alle Inserate gelten als text_ok",
            level="warning",
        )
        async with session_scope() as session:
            for listing_id in listing_ids:
                listing = await session.get(Listing, listing_id)
                if listing:
                    listing.status = ListingStatus.text_ok
        await ctx.finish_stage("text", ok=len(listing_ids), rejected=0, errors=0, skipped=True)
        return list(listing_ids)

    client = client_for("text", ctx.settings)
    semaphore = asyncio.Semaphore(max(1, app_settings.text_concurrency))
    counters = {"ok": 0, "rejected": 0, "errors": 0}
    accepted: list[int] = []

    async def analyse(listing_id: int) -> None:
        ctx.raise_if_cancelled()
        async with semaphore:
            async with session_scope() as session:
                listing = await session.get(Listing, listing_id)
                if listing is None:
                    return
                payload = _as_dict(listing)

            try:
                result = await client.generate_json(
                    model,
                    text_prompt(payload, exclusions, criteria),
                    system=TEXT_SYSTEM,
                )
            except OllamaError as exc:
                counters["errors"] += 1
                await ctx.log(f"Textmodell-Fehler bei Inserat {listing_id}: {exc}", level="error")
                async with session_scope() as session:
                    listing = await session.get(Listing, listing_id)
                    if listing:
                        listing.status = ListingStatus.error
                        listing.error_message = f"Text-Stage: {exc}"
                await ctx.advance("text")
                return

            verdict = str(result.get("verdict", "ok")).lower()
            rejected = verdict.startswith("reject")
            async with session_scope() as session:
                listing = await session.get(Listing, listing_id)
                if listing is None:
                    return
                listing.text_verdict = result
                listing.text_reasoning = str(result.get("reasoning") or "")
                listing.status = (
                    ListingStatus.text_rejected if rejected else ListingStatus.text_ok
                )
            if rejected:
                counters["rejected"] += 1
            else:
                counters["ok"] += 1
                accepted.append(listing_id)
            await ctx.advance("text")

    await asyncio.gather(*(analyse(i) for i in listing_ids))
    await ctx.finish_stage("text", **counters)
    await ctx.log(
        f"Text-Analyse fertig: {counters['ok']} ok, {counters['rejected']} abgelehnt, "
        f"{counters['errors']} Fehler"
    )
    return accepted
