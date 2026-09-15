"""Stufe 4 - Klassifizierung in die drei Zielklassen.

Regel aus dem Plan: Bei gleichzeitigem Treffer in "unpassender Zustand" UND
"unpassende Optik" gewinnt immer "unpassender Zustand".
"""

from __future__ import annotations

from sqlalchemy import select

from app.db import session_scope
from app.models import FinalClass, Listing, ListingStatus
from app.pipeline.context import RunContext


def classify(listing: Listing) -> FinalClass | None:
    text_rejected = bool(
        listing.text_verdict
        and str(listing.text_verdict.get("verdict", "")).lower().startswith("reject")
    )
    if text_rejected or listing.status == ListingStatus.text_rejected:
        # Zustand schlaegt Optik - unabhaengig vom Optik-Ergebnis.
        return FinalClass.unpassender_zustand

    optical_rejected = bool(
        listing.optical_verdict
        and str(listing.optical_verdict.get("verdict", "")).lower().startswith("reject")
    )
    if optical_rejected or listing.status == ListingStatus.optical_rejected:
        return FinalClass.unpassende_optik

    if listing.status in (ListingStatus.optical_ok, ListingStatus.analyzed, ListingStatus.text_ok):
        return FinalClass.passend
    return None


async def run_stage(ctx: RunContext, listing_ids: list[int]) -> dict[str, list[int]]:
    await ctx.start_stage("classify", total=len(listing_ids))
    buckets: dict[str, list[int]] = {c.value: [] for c in FinalClass}

    async with session_scope() as session:
        rows = (
            await session.execute(select(Listing).where(Listing.id.in_(listing_ids or [-1])))
        ).scalars().all()
        for listing in rows:
            final = classify(listing)
            if final is None:
                continue
            listing.final_class = final
            if listing.status != ListingStatus.error:
                listing.status = ListingStatus.analyzed
            buckets[final.value].append(listing.id)

    for _ in listing_ids:
        await ctx.advance("classify")
    counts = {key: len(value) for key, value in buckets.items()}
    await ctx.finish_stage("classify", **counts)
    await ctx.log(
        "Klassifizierung: "
        f"{counts['passend']} passend, {counts['unpassende_optik']} unpassende Optik, "
        f"{counts['unpassender_zustand']} unpassender Zustand"
    )
    return buckets
