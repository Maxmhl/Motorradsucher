"""Ergebnis-Ansicht: drei Klassen, Top-N-Begrenzung, Filter und Sortierung."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_session
from app.models import FinalClass, Listing
from app.schemas import ListingOut, ListingPage
from app.settings_store import get_all

router = APIRouter(prefix="/api/listings", tags=["listings"])

SORT_FIELDS = {
    "score": Listing.rank_score,
    "price": Listing.price,
    "km": Listing.km,
    "year": Listing.year,
    "first_seen": Listing.first_seen,
}


def _to_out(listing: Listing) -> ListingOut:
    out = ListingOut.model_validate(listing)
    out.site = listing.site.name if listing.site else None
    out.thumbnail_url = (
        f"/api/listings/{listing.id}/thumbnail" if listing.thumbnail_path else None
    )
    return out


@router.get("", response_model=ListingPage)
async def list_listings(
    final_class: str | None = Query(
        None, description="passend | unpassende_optik | unpassender_zustand"
    ),
    sort: str = Query("score"),
    direction: str = Query("desc"),
    price_max: int | None = None,
    km_max: int | None = None,
    year_min: int | None = None,
    search: str | None = None,
    show_all: bool = Query(False, description="Top-N-Begrenzung der Reject-Klassen aufheben"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> ListingPage:
    query = select(Listing).options(selectinload(Listing.site), selectinload(Listing.images))
    count_query = select(func.count(Listing.id))

    if final_class:
        try:
            target = FinalClass(final_class)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Unbekannte Klasse") from exc
        query = query.where(Listing.final_class == target)
        count_query = count_query.where(Listing.final_class == target)
    if price_max is not None:
        query = query.where(Listing.price <= price_max)
        count_query = count_query.where(Listing.price <= price_max)
    if km_max is not None:
        query = query.where(Listing.km <= km_max)
        count_query = count_query.where(Listing.km <= km_max)
    if year_min is not None:
        query = query.where(Listing.year >= year_min)
        count_query = count_query.where(Listing.year >= year_min)
    if search:
        pattern = f"%{search}%"
        condition = Listing.title.ilike(pattern) | Listing.description.ilike(pattern)
        query = query.where(condition)
        count_query = count_query.where(condition)

    column = SORT_FIELDS.get(sort, Listing.rank_score)
    order = column.desc() if direction == "desc" else column.asc()
    # NULL-Scores immer ans Ende, sonst stehen ungerankte Inserate oben.
    query = query.order_by(column.is_(None), order, Listing.id.desc())

    total = (await session.execute(count_query)).scalar_one()

    # Stufe 6: In den Reject-Klassen sind standardmaessig nur die Top N sichtbar.
    hidden = 0
    settings_values = await get_all(session)
    top_n = int(settings_values.get("top_n_rejected") or 3)
    if (
        final_class
        in (FinalClass.unpassende_optik.value, FinalClass.unpassender_zustand.value)
        and not show_all
    ):
        hidden = max(0, total - top_n)
        limit = min(limit, max(0, top_n - offset))

    if limit <= 0:
        return ListingPage(items=[], total=total, hidden=hidden)

    rows = await session.execute(query.offset(offset).limit(limit))
    return ListingPage(
        items=[_to_out(listing) for listing in rows.scalars().all()],
        total=total,
        hidden=hidden,
    )


@router.get("/{listing_id}", response_model=ListingOut)
async def get_listing(
    listing_id: int, session: AsyncSession = Depends(get_session)
) -> ListingOut:
    rows = await session.execute(
        select(Listing)
        .options(selectinload(Listing.site), selectinload(Listing.images))
        .where(Listing.id == listing_id)
    )
    listing = rows.scalar_one_or_none()
    if listing is None:
        raise HTTPException(status_code=404, detail="Inserat nicht gefunden")
    return _to_out(listing)


@router.get("/{listing_id}/thumbnail")
async def get_thumbnail(listing_id: int, session: AsyncSession = Depends(get_session)):
    from fastapi.responses import FileResponse

    from app.config import settings as app_settings

    listing = await session.get(Listing, listing_id)
    if listing is None or not listing.thumbnail_path:
        raise HTTPException(status_code=404, detail="Kein Vorschaubild vorhanden")
    path = app_settings.thumb_dir / listing.thumbnail_path
    if not path.exists():
        raise HTTPException(status_code=404, detail="Vorschaubild wurde gelöscht")
    return FileResponse(path, media_type="image/webp", headers={"Cache-Control": "max-age=86400"})
