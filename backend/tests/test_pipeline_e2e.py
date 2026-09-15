"""End-to-End-Test der Pipeline: Fetcher und Ollama gemockt, alles andere echt.

Deckt die Stufen 1-6 ab, inklusive Dedup, Klassifizierung, Bildloeschung und
dem dauerhaft erhaltenen Thumbnail.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image as PILImage
from sqlalchemy import select

from app.config import settings
from app.db import init_db, session_scope
from app.models import FinalClass, Image, Listing, ListingStatus
from app.pipeline import stage_scrape, stage_vision
from app.pipeline.runner import runner
from app.settings_store import set_many

FIXTURES = Path(__file__).parent / "fixtures"


class FakeFetcher:
    """Liefert die Fixtures statt echter HTTP-Abrufe."""

    def __init__(self, *_args, **_kwargs) -> None:
        self.calls: list[str] = []

    async def __aenter__(self) -> FakeFetcher:
        return self

    async def __aexit__(self, *_exc) -> None:
        return None

    # Jede Anzeige hat eine eigene Detailseite, damit die drei Zielklassen
    # tatsaechlich unterschiedlich durchlaufen werden.
    DETAILS = {
        "yamaha-mt-07": "kleinanzeigen_detail.html",
        "kawasaki-z650": "kleinanzeigen_detail_kawasaki.html",
        "honda-cb500f": "kleinanzeigen_detail_unfall.html",
    }

    async def get(self, url: str, wait_for=None) -> str:
        self.calls.append(url)
        if "/s-anzeige/" in url:
            for slug, name in self.DETAILS.items():
                if slug in url:
                    return (FIXTURES / name).read_text(encoding="utf-8")
            raise AssertionError(f"Unerwartete Detail-URL im Test: {url}")
        if "kleinanzeigen.de" in url and "seite:" not in url:
            return (FIXTURES / "kleinanzeigen_search.html").read_text(encoding="utf-8")
        return "<html><body></body></html>"


def _png_bytes() -> bytes:
    buffer = io.BytesIO()
    PILImage.new("RGB", (900, 600), (20, 60, 180)).save(buffer, "PNG")
    return buffer.getvalue()


@pytest.fixture
async def clean_db():
    await init_db()
    async with session_scope() as session:
        for row in (await session.execute(select(Image))).scalars().all():
            await session.delete(row)
        for row in (await session.execute(select(Listing))).scalars().all():
            await session.delete(row)
    yield


@pytest.fixture
def patched(monkeypatch):
    """Netzwerk und Ollama abklemmen."""
    monkeypatch.setattr(stage_scrape, "fetcher_for", lambda kind: FakeFetcher())

    # Nur Kleinanzeigen aktiv lassen - die anderen Fixtures liefern nichts.
    from app.scrapers.config import get_sites

    sites = {k: v for k, v in get_sites().items() if k == "kleinanzeigen"}
    monkeypatch.setattr(stage_scrape, "get_sites", lambda: sites)

    async def fake_download(listing_id, urls, limit=None):
        paths = []
        for index, url in enumerate(urls[:2]):
            path = settings.image_dir / f"{listing_id}_{index}.jpg"
            PILImage.open(io.BytesIO(_png_bytes())).convert("RGB").save(path, "JPEG")
            paths.append((url, path))
        return paths

    monkeypatch.setattr(stage_scrape, "download_images", fake_download)

    class FakeOllama:
        def __init__(self, stage: str) -> None:
            self.stage = stage

        async def generate_json(self, model, prompt, **kwargs):
            if "OPTIK-KRITERIEN" in prompt:
                rejected = "Kawasaki" in prompt.split("INSERAT", 1)[-1]
                return {
                    "verdict": "rejected" if rejected else "ok",
                    "confidence": 0.8,
                    "reasoning": "Testurteil Optik",
                }
            if "KLASSE:" in prompt:
                import re

                ids = [int(i) for i in re.findall(r"- id: (\d+)", prompt)]
                return {
                    "rankings": [
                        {"id": i, "score": 90 - n * 5, "reasoning": "Testbegründung"}
                        for n, i in enumerate(ids)
                    ]
                }
            # Nur den Inserats-Teil ansehen - die Ausschlusskriterien im Prompt
            # enthalten dieselben Stichwoerter und wuerden sonst jedes Inserat
            # ablehnen.
            listing_part = prompt.split("INSERAT", 1)[-1]
            rejected = "Unfallschaden" in listing_part or "Bastler" in listing_part
            return {
                "verdict": "rejected" if rejected else "ok",
                "confidence": 0.9,
                "findings": ["Unfallschaden"] if rejected else [],
                "reasoning": "Testurteil Text",
            }

        async def generate_text(self, model, prompt, **kwargs):
            return "Blauer Rahmen, blaue Felgen, keine sichtbaren Kratzer."

    monkeypatch.setattr("app.pipeline.stage_text.client_for", lambda s, *_a, **_k: FakeOllama(s))
    monkeypatch.setattr(stage_vision, "client_for", lambda s, *_a, **_k: FakeOllama(s))
    monkeypatch.setattr("app.pipeline.stage_rank.client_for", lambda s, *_a, **_k: FakeOllama(s))


async def _configure() -> None:
    async with session_scope() as session:
        await set_many(
            session,
            {
                "text_model": "test-text",
                "vision_model": "test-vision",
                "interpretation_model": "test-interpret",
                "ranking_model": "test-rank",
                "criteria": {
                    "budget_max": 5500,
                    "year_min": 2018,
                    "km_max": 30000,
                    "models": ["Yamaha MT-07"],
                },
                "top_n_rejected": 3,
            },
        )


async def _run_once() -> int:
    run_id = await runner.start()
    await runner._task
    return run_id


async def test_full_pipeline(clean_db, patched):
    await _configure()
    await _run_once()

    async with session_scope() as session:
        listings = (await session.execute(select(Listing))).scalars().all()

        # Die Fixture-Suchseite hat 3 Treffer; alle Detailseiten liefern dasselbe
        # MT-07-Detail, sodass Preis/km/Baujahr den Vorfilter passieren.
        assert len(listings) == 3
        assert all(ls.final_class is not None for ls in listings)
        assert all(ls.status == ListingStatus.analyzed for ls in listings)
        assert all(ls.rank_score is not None for ls in listings)
        assert all(ls.rank_position is not None for ls in listings)

        # Stufe 5: Bilddateien geloescht, Beschreibungen bleiben.
        images = (await session.execute(select(Image))).scalars().all()
        assert images, "Es sollten Bilder angelegt worden sein"
        assert all(img.local_path is None for img in images)
        assert all(img.deleted_at is not None for img in images)
        assert all(img.source_url for img in images)

        # Nur Inserate, die bis Stufe 3 gekommen sind, haben Bildbeschreibungen -
        # ein textlich abgelehntes Inserat wird gar nicht erst angeschaut.
        analysed_ids = {
            ls.id for ls in listings if ls.final_class != FinalClass.unpassender_zustand
        }
        assert analysed_ids
        assert all(
            img.vision_description for img in images if img.listing_id in analysed_ids
        )

        # Thumbnail bleibt als dauerhafte Vorschau erhalten.
        for listing in listings:
            assert listing.thumbnail_path
            assert (settings.thumb_dir / listing.thumbnail_path).exists()

    # Vollbilder sind wirklich von der Platte verschwunden.
    assert not list(settings.image_dir.glob("*.jpg"))


async def test_rerun_deduplicates(clean_db, patched):
    """Bereits analysierte Links werden nie erneut analysiert."""
    await _configure()
    await _run_once()

    async with session_scope() as session:
        first = (await session.execute(select(Listing))).scalars().all()
        ids_before = {ls.id for ls in first}
        thumbs_before = {ls.id: ls.thumbnail_path for ls in first}

    await _run_once()

    async with session_scope() as session:
        second = (await session.execute(select(Listing))).scalars().all()
        assert {ls.id for ls in second} == ids_before, "Kein Inserat darf doppelt angelegt werden"
        assert {ls.id: ls.thumbnail_path for ls in second} == thumbs_before


async def test_zustand_beats_optik_end_to_end(clean_db, patched):
    """Ein Inserat mit Unfall-Hinweis landet in 'unpassender Zustand'."""
    await _configure()
    await _run_once()

    async with session_scope() as session:
        rows = (await session.execute(select(Listing))).scalars().all()
        by_title = {ls.title or "": ls for ls in rows}

    unfall = next(ls for title, ls in by_title.items() if "Unfallschaden" in title)
    assert unfall.final_class == FinalClass.unpassender_zustand
    # Nach Text-Ablehnung findet gar keine Bild-Analyse statt.
    assert unfall.optical_verdict is None


async def test_three_classes_are_populated(clean_db, patched):
    """Jede der drei Zielklassen bekommt genau ein Inserat aus den Fixtures."""
    await _configure()
    await _run_once()

    async with session_scope() as session:
        rows = (await session.execute(select(Listing))).scalars().all()
        by_class = {str(ls.final_class): ls.title for ls in rows}

    assert set(by_class) == {c.value for c in FinalClass}
    assert "MT-07" in by_class["passend"]
    assert "Z650" in by_class["unpassende_optik"]
    assert "CB500F" in by_class["unpassender_zustand"]
