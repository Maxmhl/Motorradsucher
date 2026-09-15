"""API-Tests gegen die echte ASGI-App (ohne Netzwerk, ohne Ollama)."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app import scheduler as scheduler_mod
from app.db import init_db, session_scope
from app.main import app
from app.models import FinalClass, Image, Listing, ListingStatus, Run, RunStatus, Site


@pytest.fixture
async def client():
    """App-Client mit laufendem Scheduler - je Test ein eigener Event-Loop."""
    await init_db()
    scheduler_mod.start()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as async_client:
            yield async_client
    finally:
        # Der Scheduler haengt am Event-Loop dieses Tests und muss mit ihm enden.
        if scheduler_mod.scheduler.get_job(scheduler_mod.JOB_ID):
            scheduler_mod.scheduler.remove_job(scheduler_mod.JOB_ID)
        scheduler_mod.shutdown()


@pytest.fixture
async def seeded():
    """Ein Inserat je Zielklasse, plus zwei Extras in den Reject-Klassen."""
    await init_db()
    async with session_scope() as session:
        for row in (await session.execute(select(Image))).scalars().all():
            await session.delete(row)
        for row in (await session.execute(select(Listing))).scalars().all():
            await session.delete(row)

    async with session_scope() as session:
        site = (
            await session.execute(select(Site).where(Site.key == "testsite"))
        ).scalar_one_or_none()
        if site is None:
            site = Site(key="testsite", name="Testseite", search_url_template="https://x/{query}")
            session.add(site)
        await session.flush()
        run = Run(status=RunStatus.finished, stage_stats={"scrape": {"new": 7}})
        session.add(run)
        await session.flush()

        plan = [
            (FinalClass.passend, 2),
            (FinalClass.unpassende_optik, 5),
            (FinalClass.unpassender_zustand, 5),
        ]
        for final, count in plan:
            for index in range(count):
                listing = Listing(
                    url=f"https://x/{final.value}/{index}",
                    site_id=site.id,
                    title=f"{final.value} #{index}",
                    price=4000 + index * 100,
                    year=2019,
                    km=15000 + index * 1000,
                    status=ListingStatus.analyzed,
                    final_class=final,
                    text_verdict={"verdict": "ok", "confidence": 0.9},
                    optical_verdict={"verdict": "ok", "confidence": 0.8},
                    rank_score=100 - index,
                    rank_position=index + 1,
                    run_id=run.id,
                )
                session.add(listing)
                await session.flush()
                session.add(
                    Image(
                        listing_id=listing.id,
                        source_url=f"https://img/{index}.jpg",
                        vision_description="Blauer Rahmen.",
                    )
                )
    yield


async def test_health(client):
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_listings_include_site_name_and_images(client, seeded):
    """Regression: `site` ist im Schema der Name, nicht das ORM-Objekt."""
    response = await client.get("/api/listings", params={"final_class": "passend"})
    assert response.status_code == 200
    body = response.json()

    assert body["total"] == 2
    first = body["items"][0]
    assert first["site"] == "Testseite"
    assert first["images"][0]["vision_description"] == "Blauer Rahmen."
    assert first["final_class"] == "passend"


async def test_reject_classes_are_limited_to_top_n(client, seeded):
    """Stufe 6: In den Reject-Klassen sind nur die Top 3 sichtbar."""
    for target in ("unpassende_optik", "unpassender_zustand"):
        response = await client.get("/api/listings", params={"final_class": target})
        body = response.json()
        assert body["total"] == 5
        assert len(body["items"]) == 3
        assert body["hidden"] == 2

        full = await client.get(
            "/api/listings", params={"final_class": target, "show_all": True}
        )
        assert len(full.json()["items"]) == 5


async def test_passend_is_not_limited(client, seeded):
    body = (await client.get("/api/listings", params={"final_class": "passend"})).json()
    assert len(body["items"]) == body["total"] == 2
    assert body["hidden"] == 0


async def test_listings_sorted_by_score_desc(client, seeded):
    body = (
        await client.get("/api/listings", params={"final_class": "unpassende_optik"})
    ).json()
    scores = [item["rank_score"] for item in body["items"]]
    assert scores == sorted(scores, reverse=True)


async def test_listings_filters(client, seeded):
    body = (
        await client.get("/api/listings", params={"final_class": "passend", "price_max": 4000})
    ).json()
    assert body["total"] == 1

    body = (
        await client.get("/api/listings", params={"final_class": "passend", "search": "#1"})
    ).json()
    assert body["total"] == 1


async def test_unknown_class_is_rejected(client):
    response = await client.get("/api/listings", params={"final_class": "quatsch"})
    assert response.status_code == 400


async def test_settings_roundtrip_merges_nested_criteria(client):
    """Ein Teil-Update der Kriterien darf die übrigen Felder nicht löschen."""
    before = (await client.get("/api/settings")).json()
    assert before["criteria"]["year_min"] == 2018

    response = await client.put("/api/settings", json={"criteria": {"budget_max": 6500}})
    assert response.status_code == 200
    criteria = response.json()["settings"]["criteria"]
    assert criteria["budget_max"] == 6500
    assert criteria["year_min"] == 2018
    assert criteria["models"] == before["criteria"]["models"]


async def test_invalid_cron_is_reported_not_raised(client):
    response = await client.put(
        "/api/settings", json={"schedule_enabled": True, "schedule_cron": "kaputt"}
    )
    assert response.status_code == 200
    schedule = response.json()["schedule"]
    assert schedule["enabled"] is False
    assert schedule["error"]


async def test_valid_cron_schedules_next_run(client):
    response = await client.put(
        "/api/settings", json={"schedule_enabled": True, "schedule_cron": "0 7 * * *"}
    )
    schedule = response.json()["schedule"]
    assert schedule["enabled"] is True
    assert schedule["next_run"]


async def test_sites_endpoint_lists_configured_scrapers(client):
    body = (await client.get("/api/settings/sites")).json()
    assert {site["key"] for site in body} == {"kleinanzeigen", "mobile_de", "tausendps"}


async def test_dashboard_reports_unreachable_ollama(client):
    """Ohne laufendes Ollama liefert das Dashboard einen Hinweis statt 500."""
    body = (await client.get("/api/dashboard")).json()
    assert body["runner"]["busy"] is False
    assert "gesamt" in body["counts"]
    assert body["ollama"] and body["ollama"][0]["reachable"] is False


async def test_models_endpoint_degrades_gracefully(client):
    body = (await client.get("/api/models")).json()
    assert body["models"] == []
    assert body["error"]
    assert body["endpoints"][0]["reachable"] is False
