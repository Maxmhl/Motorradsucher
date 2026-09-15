"""Stufe 5 - Bilder loeschen.

Nach abgeschlossener Bild-Analyse werden die lokal gespeicherten Vollbilder
geloescht und `images.deleted_at` gesetzt. Die Vision-Beschreibungen, der Link
und das kleine Vorschaubild bleiben dauerhaft erhalten.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from app.db import session_scope
from app.images import delete_file
from app.models import Image
from app.pipeline.context import RunContext


async def run_stage(ctx: RunContext, listing_ids: list[int]) -> int:
    async with session_scope() as session:
        rows = (
            await session.execute(
                select(Image).where(
                    Image.listing_id.in_(listing_ids or [-1]),
                    Image.deleted_at.is_(None),
                )
            )
        ).scalars().all()
        targets = [(r.id, r.local_path) for r in rows]

    await ctx.start_stage("cleanup", total=len(targets))
    deleted = 0
    now = datetime.now(UTC)
    async with session_scope() as session:
        for image_id, local_path in targets:
            if delete_file(local_path):
                deleted += 1
            image = await session.get(Image, image_id)
            if image:
                image.local_path = None
                image.deleted_at = now
            await ctx.advance("cleanup")

    await ctx.finish_stage("cleanup", deleted=deleted)
    await ctx.log(f"{deleted} Bilddatei(en) gelöscht, Beschreibungen bleiben erhalten")
    return deleted


async def purge_orphans() -> int:
    """Raeumt Bilddateien auf, die ein abgebrochener Run hinterlassen hat."""
    from app.config import settings

    async with session_scope() as session:
        rows = await session.execute(select(Image.local_path).where(Image.local_path.is_not(None)))
        referenced = {p for p in rows.scalars().all() if p}

    removed = 0
    for path in settings.image_dir.glob("*.jpg"):
        if str(path) not in referenced:
            delete_file(path)
            removed += 1
    return removed
