"""Selektor-Pruefung gegen eine echte Ergebnisseite oder eine HTML-Datei.

    python -m app.scrapers.check --site kleinanzeigen
    python -m app.scrapers.check --site kleinanzeigen --file gespeichert.html
    python -m app.scrapers.check --site kleinanzeigen --url https://... --detail

Zeigt, welche Selektoren greifen - nach einer Layout-Aenderung reicht es,
sites.yaml anzupassen und diesen Befehl erneut laufen zu lassen.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from app.pipeline.stage_scrape import build_search_params
from app.scrapers.config import get_sites
from app.scrapers.fetchers import fetcher_for
from app.scrapers.parser import parse_detail_page, parse_search_page


async def _load(cfg, url: str, wait_for: list[str]) -> str:
    async with fetcher_for(cfg.fetcher) as fetcher:
        return await fetcher.get(url, wait_for)


async def main() -> int:
    parser = argparse.ArgumentParser(description="Scraper-Selektoren prüfen")
    parser.add_argument("--site", required=True, help="Schlüssel aus sites.yaml")
    parser.add_argument("--url", help="konkrete URL statt der generierten Such-URL")
    parser.add_argument("--file", help="lokale HTML-Datei statt eines Abrufs")
    parser.add_argument("--detail", action="store_true", help="als Detailseite parsen")
    parser.add_argument("--query", default="Yamaha MT-07")
    parser.add_argument("--price-max", type=int, default=5000)
    parser.add_argument("--year-min", type=int, default=2018)
    parser.add_argument("--km-max", type=int, default=30000)
    args = parser.parse_args()

    sites = get_sites()
    if args.site not in sites:
        print(f"Unbekannte Seite {args.site!r}. Verfügbar: {', '.join(sites)}")
        return 2
    cfg = sites[args.site]

    params = build_search_params(
        {"budget_max": args.price_max, "year_min": args.year_min, "km_max": args.km_max},
        args.query,
    )
    url = args.url or cfg.search_url(params)

    if args.file:
        html = Path(args.file).read_text(encoding="utf-8", errors="ignore")
        print(f"Quelle: Datei {args.file}")
    else:
        print(f"Quelle: {url}  (fetcher={cfg.fetcher})")
        wait_for = cfg.detail_selectors["wait_for"] if args.detail else cfg.wait_for
        html = await _load(cfg, url, wait_for)
    print(f"HTML-Größe: {len(html)} Zeichen\n")

    if args.detail:
        detail = parse_detail_page(html, url, cfg)
        for field, value in vars(detail).items():
            if field == "description":
                value = (value or "")[:300] + ("…" if len(value or "") > 300 else "")
            if field == "image_urls":
                print(f"  image_urls    : {len(value)} Bild(er)")
                for image in value[:3]:
                    print(f"      - {image}")
                continue
            print(f"  {field:<14}: {value}")
        missing = [f for f in ("title", "description") if not getattr(detail, f)]
        if missing:
            print(f"\n  LEER: {', '.join(missing)} → sites.yaml → {cfg.key}.detail prüfen")
        return 0 if not missing else 1

    stubs = parse_search_page(html, cfg)
    print(f"  {len(stubs)} Treffer erkannt")
    for stub in stubs[:5]:
        print(f"    - {stub.title[:60]!r} | {stub.price} EUR | {stub.url}")
    if not stubs:
        print(f"\n  KEINE TREFFER → sites.yaml → {cfg.key}.list.item / .link prüfen")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
