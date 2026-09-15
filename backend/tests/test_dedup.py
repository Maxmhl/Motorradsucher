"""Seitenuebergreifende Dedup-Erkennung (Stufe 1): dasselbe Fahrzeug auf
mehreren Portalen darf die KI-Stufen nur einmal durchlaufen."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.db import init_db, session_scope
from app.models import FinalClass, Listing, ListingStatus, Run, Site
from app.pipeline.context import RunContext
from app.pipeline.stage_scrape import _store_listing


def _detail(**overrides):
    base = dict(
        url="https://example.org/x",
        title="Yamaha MT-07 ABS, Topzustand",
        description="",
        price=4800,
        year=2019,
        km=6400,
        model=None,
        location="",
        image_urls=[],
    )
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture
async def clean_db():
    await init_db()
    async with session_scope() as session:
        for row in (await session.execute(select(Listing))).scalars().all():
            row.duplicate_of_id = None
        await session.flush()
        for row in (await session.execute(select(Listing))).scalars().all():
            await session.delete(row)
        for row in (await session.execute(select(Site))).scalars().all():
            await session.delete(row)


async def _run_id() -> int:
    async with session_scope() as session:
        run = Run()
        session.add(run)
        await session.flush()
        return run.id


@pytest.fixture
async def ctx(clean_db):
    return RunContext(run_id=await _run_id(), settings={})


async def _site_id(key: str) -> int:
    async with session_scope() as session:
        site = Site(key=key, name=key, search_url_template="https://x/{query}")
        session.add(site)
        await session.flush()
        return site.id


async def test_second_site_marked_as_duplicate_before_original_is_classified(clean_db, ctx):
    """Original noch unbewertet -> Dublette wartet (status=duplicate, final_class=None)."""
    site_a = await _site_id("kleinanzeigen")
    site_b = await _site_id("tausendps")

    first_id, first_dup = await _store_listing(
        ctx, cfg=None, site_id=site_a, detail=_detail(url="https://kleinanzeigen/x")
    )
    assert first_dup is False

    second_id, second_dup = await _store_listing(
        ctx,
        cfg=None,
        site_id=site_b,
        detail=_detail(
            url="https://1000ps/x",
            title="Yamaha MT 07 ABS Topzustand!!",  # leicht anders formuliert
            km=6250,  # rundet in denselben 1000er-Bucket
        ),
    )
    assert second_dup is True

    async with session_scope() as session:
        original = await session.get(Listing, first_id)
        dup = await session.get(Listing, second_id)
        assert dup.duplicate_of_id == original.id
        assert dup.status == ListingStatus.duplicate
        assert dup.final_class is None  # Original noch nicht bewertet


async def test_second_site_inherits_finished_classification(clean_db, ctx):
    """Original bereits fertig bewertet -> Dublette uebernimmt sofort Klasse/Score."""
    site_a = await _site_id("kleinanzeigen")
    site_b = await _site_id("tausendps")

    first_id, _ = await _store_listing(
        ctx, cfg=None, site_id=site_a, detail=_detail(url="https://kleinanzeigen/y")
    )
    async with session_scope() as session:
        original = await session.get(Listing, first_id)
        original.final_class = FinalClass.passend
        original.rank_score = 88.0
        original.status = ListingStatus.analyzed

    second_id, second_dup = await _store_listing(
        ctx,
        cfg=None,
        site_id=site_b,
        detail=_detail(url="https://1000ps/y"),
    )
    assert second_dup is True

    async with session_scope() as session:
        dup = await session.get(Listing, second_id)
        assert dup.final_class == FinalClass.passend
        assert dup.rank_score == 88.0
        assert dup.status == ListingStatus.analyzed
        assert "kleinanzeigen/y" in (dup.rank_reasoning or "")


async def test_different_vehicle_is_not_flagged_as_duplicate(clean_db, ctx):
    site_a = await _site_id("kleinanzeigen")
    site_b = await _site_id("tausendps")

    await _store_listing(
        ctx, cfg=None, site_id=site_a, detail=_detail(url="https://kleinanzeigen/z")
    )
    _, is_dup = await _store_listing(
        ctx,
        cfg=None,
        site_id=site_b,
        detail=_detail(url="https://1000ps/z", title="Suzuki SV650", price=5200),
    )
    assert is_dup is False
