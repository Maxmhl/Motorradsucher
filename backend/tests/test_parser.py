"""Parser-Tests gegen gespeicherte HTML-Fixtures - komplett netzwerkfrei."""

from __future__ import annotations

import pytest

from app.pipeline.stage_scrape import passes_local_prefilter
from app.scrapers.config import get_sites
from app.scrapers.parser import (
    ListingDetail,
    parse_detail_page,
    parse_number,
    parse_search_page,
    parse_year,
)

CRITERIA_DEFAULT = {"budget_max": 5000, "year_min": 2018, "km_max": 30000}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("4.850 € VB", 4850),
        ("5.200 €", 5200),
        ("18.400 km", 18400),
        ("4.990,- €", 4990),
        ("12 345 km", 12345),
        ("VB", None),
        (None, None),
    ],
)
def test_parse_number(text, expected):
    assert parse_number(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [("04/2019", 2019), ("EZ 2018", 2018), ("2020", 2020), ("Baujahr unbekannt", None)],
)
def test_parse_year(text, expected):
    assert parse_year(text) == expected


def test_parse_kleinanzeigen_search(fixture_html):
    cfg = get_sites()["kleinanzeigen"]
    stubs = parse_search_page(fixture_html("kleinanzeigen_search.html"), cfg)

    assert len(stubs) == 3
    first = stubs[0]
    assert first.url.startswith("https://www.kleinanzeigen.de/s-anzeige/yamaha-mt-07")
    assert "MT-07" in first.title
    assert first.price == 4850
    assert first.location == "30159 Hannover"


def test_parse_kleinanzeigen_detail(fixture_html):
    cfg = get_sites()["kleinanzeigen"]
    url = "https://www.kleinanzeigen.de/s-anzeige/yamaha-mt-07-abs-bj-2019/2891234567-305-3421"
    detail = parse_detail_page(fixture_html("kleinanzeigen_detail.html"), url, cfg)

    assert detail.price == 4850
    assert detail.km == 18400
    assert detail.year == 2019
    assert detail.model == "MT-07"
    assert detail.location == "30159 Hannover"
    assert "Blauer Rahmen" in detail.description
    # src, data-src und srcset werden alle beruecksichtigt, data:-URLs nicht.
    assert len(detail.image_urls) == 3
    assert all(u.startswith("https://") for u in detail.image_urls)
    # Aus srcset wird nur die erste URL genommen.
    assert " " not in detail.image_urls[2]


def test_parse_tausendps_search(fixture_html):
    cfg = get_sites()["tausendps"]
    stubs = parse_search_page(fixture_html("tausendps_search.html"), cfg)

    assert len(stubs) == 2
    assert stubs[0].price == 5499
    # ?pos=N ist entfernt - sonst gilt derselbe Treffer beim nächsten Run als neu.
    assert stubs[0].url == "https://www.1000ps.de/gebrauchtes-motorrad-3598756-yamaha-mt-07"
    assert "Yamaha MT-07" in stubs[0].title


def test_parse_tausendps_detail(fixture_html):
    """Lazyload (data-src) und Platzhalterbilder - live gegen 1000PS verifiziert."""
    cfg = get_sites()["tausendps"]
    url = "https://www.1000ps.de/gebrauchtes-motorrad-3598756-yamaha-mt-07"
    detail = parse_detail_page(fixture_html("tausendps_detail.html"), url, cfg)

    assert detail.title == "Yamaha MT-07"
    assert detail.year == 2017
    assert detail.km == 40252
    assert "64354 Reinheim" in detail.location
    assert "Sportschalldämpfer" in detail.description
    # Nur echte Fahrzeugbilder: nopic-Platzhalter und das Herz-Icon fliegen raus.
    assert len(detail.image_urls) == 2
    assert all("1000ps.net/g-" in u for u in detail.image_urls)


def test_tausendps_listing_is_prefiltered_locally():
    """Dieses reale Inserat (2017, 40.252 km) muss der Vorfilter aussortieren."""
    cfg = get_sites()["tausendps"]
    detail = ListingDetail(url="u", year=2017, km=40252, price=5499)
    ok, reason = passes_local_prefilter(cfg, detail, CRITERIA_DEFAULT)
    assert ok is False
    assert reason


def test_detail_falls_back_to_description(fixture_html):
    """Baujahr/km stehen bei vielen Inseraten nur im Freitext."""
    cfg = get_sites()["kleinanzeigen"]
    html = """<html><body>
      <h1 id="viewad-title">Kawasaki Z650</h1>
      <p id="viewad-description-text">Baujahr 2021, gelaufen 9.800 km, Topzustand.</p>
    </body></html>"""
    detail = parse_detail_page(html, "https://example.org/x", cfg)
    assert detail.year == 2021
    assert detail.km == 9800
