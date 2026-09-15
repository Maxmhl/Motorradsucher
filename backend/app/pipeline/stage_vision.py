"""Stufe 3 - Bild-Analyse.

Zweistufig, wie im Plan: ein Vision-Modell beschreibt jedes Bild in Textform,
ein zweites Textmodell interpretiert die aggregierten Beschreibungen gegen die
frei definierbaren Optik-Kriterien. Die Vision-Beschreibungen bleiben dauerhaft
erhalten, auch nachdem die Bilddateien in Stufe 5 geloescht wurden.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from sqlalchemy import select

from app.config import settings as app_settings
from app.db import session_scope
from app.models import Image, Listing, ListingStatus
from app.ollama import OllamaError, client_for
from app.pipeline.context import RunContext
from app.pipeline.prompts import (
    INTERPRET_SYSTEM,
    VISION_PROMPT,
    VISION_SYSTEM,
    interpret_prompt,
)


async def _describe_images(
    ctx: RunContext, listing_id: int, vision_model: str
) -> list[str]:
    """Beschreibt alle Bilder eines Inserats und legt das Thumbnail an."""
    client = client_for("vision")

    async with session_scope() as session:
        rows = (
            await session.execute(
                select(Image).where(Image.listing_id == listing_id).order_by(Image.position)
            )
        ).scalars().all()
        images = [(r.id, r.local_path, r.vision_description) for r in rows]

    if not images:
        return []

    descriptions: list[str] = []
    for image_id, local_path, existing in images:
        ctx.raise_if_cancelled()
        if existing:  # bereits beschrieben (z. B. nach Wiederaufnahme)
            descriptions.append(existing)
            continue
        if not local_path or not Path(local_path).exists():
            continue
        try:
            text = await client.generate_text(
                vision_model,
                VISION_PROMPT,
                system=VISION_SYSTEM,
                images=[Path(local_path)],
                temperature=0.2,
            )
        except OllamaError as exc:
            await ctx.log(f"Vision-Modell-Fehler (Bild {image_id}): {exc}", level="warning")
            continue
        if text:
            descriptions.append(text)
            async with session_scope() as session:
                image = await session.get(Image, image_id)
                if image:
                    image.vision_description = text
    return descriptions


async def run_stage(ctx: RunContext, listing_ids: list[int]) -> list[int]:
    """Bewertet die Optik. Gibt die IDs mit optical_ok zurueck."""
    vision_model = (ctx.settings.get("vision_model") or "").strip()
    interpret_model = (ctx.settings.get("interpretation_model") or "").strip()
    optical_criteria = ctx.settings.get("optical_criteria") or ""

    await ctx.start_stage("vision", total=len(listing_ids))
    if not listing_ids:
        await ctx.finish_stage("vision", ok=0, rejected=0, errors=0)
        return []
    if not vision_model or not interpret_model:
        await ctx.log(
            "Vision- oder Interpretationsmodell fehlt - Stufe 3 übersprungen, "
            "alle Inserate gelten als optical_ok",
            level="warning",
        )
        async with session_scope() as session:
            for listing_id in listing_ids:
                listing = await session.get(Listing, listing_id)
                if listing:
                    listing.status = ListingStatus.optical_ok
        await ctx.finish_stage("vision", ok=len(listing_ids), rejected=0, errors=0, skipped=True)
        return list(listing_ids)

    interpreter = client_for("interpretation")
    semaphore = asyncio.Semaphore(max(1, app_settings.vision_concurrency))
    counters = {"ok": 0, "rejected": 0, "errors": 0, "no_images": 0}
    accepted: list[int] = []

    async def analyse(listing_id: int) -> None:
        ctx.raise_if_cancelled()
        async with semaphore:
            descriptions = await _describe_images(ctx, listing_id, vision_model)

            async with session_scope() as session:
                listing = await session.get(Listing, listing_id)
                if listing is None:
                    return
                payload = {"title": listing.title, "year": listing.year, "km": listing.km}

            if not descriptions:
                # Ohne Bilder ist die Optik nicht pruefbar - das ist kein
                # Ablehnungsgrund, sonst fielen bildlose Inserate durchs Raster.
                counters["no_images"] += 1
                async with session_scope() as session:
                    listing = await session.get(Listing, listing_id)
                    if listing:
                        listing.status = ListingStatus.optical_ok
                        listing.optical_verdict = {
                            "verdict": "ok",
                            "confidence": 0.0,
                            "reasoning": "Keine auswertbaren Bilder vorhanden.",
                        }
                        listing.optical_reasoning = "Keine auswertbaren Bilder vorhanden."
                accepted.append(listing_id)
                counters["ok"] += 1
                await ctx.advance("vision")
                return

            try:
                result = await interpreter.generate_json(
                    interpret_model,
                    interpret_prompt(payload, descriptions, optical_criteria),
                    system=INTERPRET_SYSTEM,
                )
            except OllamaError as exc:
                counters["errors"] += 1
                await ctx.log(
                    f"Interpretationsmodell-Fehler bei Inserat {listing_id}: {exc}", level="error"
                )
                async with session_scope() as session:
                    listing = await session.get(Listing, listing_id)
                    if listing:
                        listing.status = ListingStatus.error
                        listing.error_message = f"Bild-Stage: {exc}"
                await ctx.advance("vision")
                return

            rejected = str(result.get("verdict", "ok")).lower().startswith("reject")
            async with session_scope() as session:
                listing = await session.get(Listing, listing_id)
                if listing is None:
                    return
                listing.optical_verdict = result
                listing.optical_reasoning = str(result.get("reasoning") or "")
                listing.status = (
                    ListingStatus.optical_rejected if rejected else ListingStatus.optical_ok
                )
            if rejected:
                counters["rejected"] += 1
            else:
                counters["ok"] += 1
                accepted.append(listing_id)
            await ctx.advance("vision")

    await asyncio.gather(*(analyse(i) for i in listing_ids))
    await ctx.finish_stage("vision", **counters)
    await ctx.log(
        f"Bild-Analyse fertig: {counters['ok']} ok, {counters['rejected']} abgelehnt, "
        f"{counters['no_images']} ohne Bilder, {counters['errors']} Fehler"
    )
    return accepted
