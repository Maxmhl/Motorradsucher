"""Stufe 1 - Scraping.

Nutzt die websiteseitigen Filter zur Grobauswahl (keine KI). Jeder gefundene
Link wird gegen `listings.url` geprueft; nur wirklich neue Inserate werden
vollstaendig geladen. Bereits analysierte Links bleiben dauerhaft in der DB -
auch wenn das Inserat offline geht - und werden nie erneut analysiert.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote_plus

from sqlalchemy import select

from app.db import session_scope
from app.images import download_images, make_thumbnail
from app.models import Image, Listing, ListingStatus, Site
from app.pipeline.context import RunContext
from app.scrapers.config import SiteConfig, get_sites
from app.scrapers.fetchers import BlockedError, ScrapeError, fetcher_for
from app.scrapers.parser import ListingStub, parse_detail_page, parse_search_page

log = logging.getLogger(__name__)


def build_search_params(criteria: dict[str, Any], query: str) -> dict[str, Any]:
    return {
        "query": quote_plus(query) if query else "",
        "price_max": criteria.get("budget_max") or "",
        "year_min": criteria.get("year_min") or "",
        "km_max": criteria.get("km_max") or "",
        "zip_code": criteria.get("zip_code") or "",
        "radius_km": criteria.get("radius_km") or "",
    }


def passes_local_prefilter(
    cfg: SiteConfig, detail: Any, criteria: dict[str, Any]
) -> tuple[bool, str]:
    """Filter, die die Website selbst nicht anbietet (siehe prefilter_local)."""
    if "year_min" in cfg.prefilter_local and criteria.get("year_min"):
        if detail.year is not None and detail.year < int(criteria["year_min"]):
            return False, f"Baujahr {detail.year} < {criteria['year_min']}"
    if "km_max" in cfg.prefilter_local and criteria.get("km_max"):
        if detail.km is not None and detail.km > int(criteria["km_max"]):
            return False, f"{detail.km} km > {criteria['km_max']} km"
    if criteria.get("budget_max") and detail.price is not None:
        if detail.price > int(criteria["budget_max"]) * 1.05:  # kleine Toleranz für VB
            return False, f"Preis {detail.price} EUR über Budget"
    return True, ""


async def _ensure_site(cfg: SiteConfig) -> int:
    """Site-Zeile anlegen/aktualisieren und ID zurueckgeben."""
    async with session_scope() as session:
        site = (
            await session.execute(select(Site).where(Site.key == cfg.key))
        ).scalar_one_or_none()
        if site is None:
            site = Site(key=cfg.key, name=cfg.name, search_url_template=cfg.search_url_template)
            session.add(site)
        else:
            site.name = cfg.name
            site.search_url_template = cfg.search_url_template
        site.enabled = cfg.enabled
        site.filter_params = cfg.raw.get("pagination") or {}
        await session.flush()
        return site.id


async def _known_urls(urls: list[str]) -> set[str]:
    if not urls:
        return set()
    async with session_scope() as session:
        rows = await session.execute(select(Listing.url).where(Listing.url.in_(urls)))
        return set(rows.scalars().all())


async def _collect_stubs(
    ctx: RunContext, cfg: SiteConfig, fetcher: Any, criteria: dict[str, Any]
) -> list[ListingStub]:
    """Ergebnisseiten aller Suchbegriffe durchgehen."""
    queries = criteria.get("models") or [""]
    stubs: dict[str, ListingStub] = {}
    for query in queries:
        params = build_search_params(criteria, query)
        for page in range(1, cfg.max_pages + 1):
            ctx.raise_if_cancelled()
            url = cfg.search_url(params, page=page)
            try:
                html = await fetcher.get(url, cfg.wait_for)
            except BlockedError as exc:
                await ctx.log(f"{cfg.name}: {exc}", level="error")
                return list(stubs.values())
            except ScrapeError as exc:
                await ctx.log(f"{cfg.name}: Seite {page} fehlgeschlagen - {exc}", level="warning")
                break
            found = parse_search_page(html, cfg)
            if not found:
                if page == 1:
                    await ctx.log(
                        f"{cfg.name}: keine Treffer für '{query}' - Selektoren prüfen "
                        f"(sites.yaml → {cfg.key}.list.item)",
                        level="warning",
                    )
                break
            for stub in found:
                stubs.setdefault(stub.url, stub)
    return list(stubs.values())


async def _store_listing(
    ctx: RunContext, cfg: SiteConfig, site_id: int, detail: Any
) -> int | None:
    """Neues Inserat samt Bildern speichern."""
    async with session_scope() as session:
        exists = (
            await session.execute(select(Listing.id).where(Listing.url == detail.url))
        ).scalar_one_or_none()
        if exists:
            return None
        listing = Listing(
            url=detail.url,
            site_id=site_id,
            title=detail.title[:512] or None,
            model=(detail.model or None),
            price=detail.price,
            year=detail.year,
            km=detail.km,
            location=detail.location[:256] or None,
            description=detail.description or None,
            status=ListingStatus.new,
            run_id=ctx.run_id,
        )
        session.add(listing)
        await session.flush()
        listing_id = listing.id

    downloaded = await download_images(listing_id, detail.image_urls)
    if downloaded:
        # Das Vorschaubild entsteht bereits hier und nicht erst in Stufe 3:
        # textlich abgelehnte Inserate durchlaufen die Bild-Stufe nie, sollen
        # aber in der Klasse "unpassender Zustand" trotzdem eine Vorschau haben.
        thumbnail = (
            make_thumbnail(listing_id, downloaded[0][1])
            if ctx.settings.get("keep_thumbnail", True)
            else None
        )
        async with session_scope() as session:
            for position, (source_url, path) in enumerate(downloaded):
                session.add(
                    Image(
                        listing_id=listing_id,
                        source_url=source_url[:1024],
                        local_path=str(path),
                        position=position,
                    )
                )
            if thumbnail:
                listing = await session.get(Listing, listing_id)
                if listing:
                    listing.thumbnail_path = thumbnail
    return listing_id


async def run_stage(ctx: RunContext) -> list[int]:
    """Gibt die IDs der neu angelegten Inserate zurueck."""
    criteria = ctx.settings.get("criteria") or {}
    max_listings = int(ctx.settings.get("max_listings_per_run") or 200)
    sites = [cfg for cfg in get_sites().values() if cfg.enabled]

    await ctx.start_stage("scrape")
    await ctx.log(f"Starte Scraping über {len(sites)} Seite(n)")

    new_ids: list[int] = []
    totals = {"found": 0, "known": 0, "filtered": 0, "new": 0, "errors": 0}

    for cfg in sites:
        ctx.raise_if_cancelled()
        site_id = await _ensure_site(cfg)
        try:
            async with fetcher_for(cfg.fetcher) as fetcher:
                stubs = await _collect_stubs(ctx, cfg, fetcher, criteria)
                totals["found"] += len(stubs)
                await ctx.log(f"{cfg.name}: {len(stubs)} Treffer in der Ergebnisliste")

                known = await _known_urls([s.url for s in stubs])
                fresh = [s for s in stubs if s.url not in known]
                totals["known"] += len(stubs) - len(fresh)
                await ctx.log(
                    f"{cfg.name}: {len(fresh)} neu, {len(stubs) - len(fresh)} bereits bekannt"
                )

                stage = ctx.stage("scrape")
                stage["total"] = stage.get("total", 0) + len(fresh)
                await ctx.publish()

                for stub in fresh:
                    ctx.raise_if_cancelled()
                    if len(new_ids) >= max_listings:
                        await ctx.log(
                            f"Limit von {max_listings} neuen Inseraten erreicht", level="warning"
                        )
                        break
                    try:
                        html = await fetcher.get(stub.url, cfg.detail_selectors["wait_for"])
                        detail = parse_detail_page(html, stub.url, cfg)
                    except BlockedError as exc:
                        totals["errors"] += 1
                        await ctx.log(f"{cfg.name}: {exc}", level="error")
                        break
                    except ScrapeError as exc:
                        totals["errors"] += 1
                        await ctx.log(f"Detailseite fehlgeschlagen: {exc}", level="warning")
                        await ctx.advance("scrape")
                        continue

                    if not detail.price and stub.price:
                        detail.price = stub.price
                    if not detail.title:
                        detail.title = stub.title

                    ok, reason = passes_local_prefilter(cfg, detail, criteria)
                    if not ok:
                        totals["filtered"] += 1
                        await ctx.log(f"Vorfilter verworfen ({reason}): {stub.url}", level="debug")
                        await ctx.advance("scrape")
                        continue

                    listing_id = await _store_listing(ctx, cfg, site_id, detail)
                    if listing_id is not None:
                        new_ids.append(listing_id)
                        totals["new"] += 1
                    await ctx.advance("scrape")
        except Exception as exc:  # noqa: BLE001 - eine Seite darf den Run nicht kippen
            totals["errors"] += 1
            await ctx.log(f"{cfg.name}: Scraper-Fehler - {exc}", level="error")
            log.exception("Scraper-Fehler für %s", cfg.key)

    await ctx.finish_stage("scrape", **totals)
    await ctx.log(
        f"Scraping fertig: {totals['found']} gefunden, {totals['new']} neu, "
        f"{totals['known']} bekannt, {totals['filtered']} vorgefiltert"
    )
    return new_ids
