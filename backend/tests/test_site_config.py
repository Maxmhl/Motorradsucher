"""Such-URLs, Paginierung und Selektor-Konfiguration."""

from __future__ import annotations

from urllib.parse import quote_plus

from app.pipeline.stage_scrape import build_search_params, passes_local_prefilter
from app.scrapers.config import get_sites
from app.scrapers.parser import ListingDetail

CRITERIA = {"budget_max": 5000, "year_min": 2018, "km_max": 30000}


def test_all_sites_load():
    sites = get_sites()
    assert set(sites) == {"kleinanzeigen", "mobile_de", "tausendps"}
    for cfg in sites.values():
        assert cfg.search_url_template.startswith("https://")
        assert cfg.list_selectors.get("item")


def test_search_url_has_no_whitespace():
    """YAML-Folded-Scalars duerfen keine Leerzeichen in die URL bringen."""
    params = build_search_params(CRITERIA, "Yamaha MT-07")
    for cfg in get_sites().values():
        url = cfg.search_url(params)
        assert " " not in url and "\n" not in url, cfg.key
        assert "{" not in url, f"Unersetzter Platzhalter in {cfg.key}: {url}"


def test_search_url_fills_criteria():
    cfg = get_sites()["mobile_de"]
    url = cfg.search_url(build_search_params(CRITERIA, "Yamaha MT-07"))
    assert "priceTo=5000" in url
    assert "mileageTo=30000" in url
    assert "2018-01-01" in url
    assert quote_plus("Yamaha MT-07") in url


def test_pagination_query_mode():
    cfg = get_sites()["mobile_de"]
    page2 = cfg.search_url(build_search_params(CRITERIA, "MT-07"), page=2)
    assert "pageNumber=2" in page2


def test_pagination_path_mode():
    cfg = get_sites()["kleinanzeigen"]
    params = build_search_params(CRITERIA, "MT-07")
    assert "seite:" not in cfg.search_url(params, page=1)
    assert "seite:2" in cfg.search_url(params, page=2)


def test_absolute_url():
    cfg = get_sites()["kleinanzeigen"]
    assert cfg.absolute("/s-anzeige/x") == "https://www.kleinanzeigen.de/s-anzeige/x"
    assert cfg.absolute("https://other.tld/y") == "https://other.tld/y"
    assert cfg.absolute("//cdn.tld/z.jpg") == "https://cdn.tld/z.jpg"


def test_local_prefilter_applies_only_where_configured():
    """Kleinanzeigen kennt keinen URL-Filter fuer Baujahr/km - daher lokal."""
    cfg = get_sites()["kleinanzeigen"]
    assert cfg.prefilter_local == ["year_min", "km_max"]

    too_old = ListingDetail(url="u", year=2015, km=10000, price=3000)
    assert passes_local_prefilter(cfg, too_old, CRITERIA)[0] is False

    too_many_km = ListingDetail(url="u", year=2020, km=45000, price=3000)
    assert passes_local_prefilter(cfg, too_many_km, CRITERIA)[0] is False

    fits = ListingDetail(url="u", year=2020, km=12000, price=4800)
    assert passes_local_prefilter(cfg, fits, CRITERIA)[0] is True


def test_prefilter_keeps_listings_with_unknown_values():
    """Fehlende Angaben duerfen nicht zum Ausschluss fuehren."""
    cfg = get_sites()["kleinanzeigen"]
    unknown = ListingDetail(url="u", year=None, km=None, price=None)
    assert passes_local_prefilter(cfg, unknown, CRITERIA)[0] is True


def test_normalize_strips_tracking_params():
    """1000PS hängt ?pos=N an - ohne Bereinigung scheitert die Dedup-Logik."""
    cfg = get_sites()["tausendps"]
    normalized = cfg.normalize("/gebrauchtes-motorrad-3598756-yamaha-mt-07?pos=1")
    assert normalized == "https://www.1000ps.de/gebrauchtes-motorrad-3598756-yamaha-mt-07"
    # Derselbe Treffer auf einem anderen Listenplatz ergibt dieselbe URL.
    assert normalized == cfg.normalize("/gebrauchtes-motorrad-3598756-yamaha-mt-07?pos=17")


def test_normalize_keeps_meaningful_params():
    """mobile.de identifiziert Inserate über ?id= - das muss bleiben."""
    cfg = get_sites()["mobile_de"]
    url = cfg.normalize("https://suchen.mobile.de/fahrzeuge/details.html?id=123456&ref=srp")
    assert "id=123456" in url
    assert "ref=" not in url


def test_normalize_drops_fragment_and_trailing_slash():
    cfg = get_sites()["kleinanzeigen"]
    assert cfg.normalize("/s-anzeige/x/123/#gallery") == cfg.normalize("/s-anzeige/x/123")
