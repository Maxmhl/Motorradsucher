"""HTML -> strukturierte Daten. Bewusst netzwerkfrei, damit gegen gespeicherte
HTML-Fixtures getestet werden kann (siehe backend/tests/fixtures)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from bs4 import BeautifulSoup, Tag

from app.scrapers.config import SiteConfig

# --------------------------------------------------------------------------
# Wertextraktion (deutsche Zahlen-/Datumsformate)
# --------------------------------------------------------------------------

_NUM = re.compile(r"\d[\d.\s']*(?:,\d+)?")


def parse_number(text: str | None) -> int | None:
    """'5.500 €' -> 5500, '12 345 km' -> 12345, 'VB 4.200' -> 4200."""
    if not text:
        return None
    match = _NUM.search(text.replace("\xa0", " "))
    if not match:
        return None
    cleaned = re.sub(r"[.\s']", "", match.group(0)).split(",")[0]
    try:
        return int(cleaned)
    except ValueError:
        return None


def parse_year(text: str | None) -> int | None:
    """'03/2019' -> 2019, 'EZ 2018' -> 2018, '2020' -> 2020."""
    if not text:
        return None
    years = [int(m.group(0)) for m in re.finditer(r"(?:19|20)\d{2}", text)]
    if not years:
        return None
    # Bei '03/2019' ist das Jahr die letzte Vierergruppe.
    return years[-1]


def clean_text(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"[ \t\xa0]+", " ", text).strip()


# --------------------------------------------------------------------------
# Selektor-Helfer (erster Treffer gewinnt)
# --------------------------------------------------------------------------


def select_one(node: Tag | BeautifulSoup, selectors: list[str]) -> Tag | None:
    for selector in selectors:
        try:
            found = node.select_one(selector)
        except Exception:  # ungueltiger Selektor in der YAML
            continue
        if found is not None:
            return found
    return None


def select_all(node: Tag | BeautifulSoup, selectors: list[str]) -> list[Tag]:
    for selector in selectors:
        try:
            found = node.select(selector)
        except Exception:
            continue
        if found:
            return found
    return []


def text_of(node: Tag | BeautifulSoup, selectors: list[str]) -> str:
    found = select_one(node, selectors)
    return clean_text(found.get_text(" ", strip=True)) if found else ""


def _first_url_from_attr(value: Any) -> str:
    """srcset kann 'url 1x, url2 2x' enthalten - erste URL nehmen."""
    if isinstance(value, list):
        value = value[0] if value else ""
    text = str(value or "").strip()
    if not text:
        return ""
    return text.split(",")[0].strip().split(" ")[0]


def select_union(node: Tag | BeautifulSoup, selectors: list[str]) -> list[Tag]:
    """Alle Selektoren vereinigen (statt erster-Treffer-gewinnt), ohne Duplikate.

    Galerien verteilen sich haeufig ueber mehrere Container - Hauptbild in dem
    einen, die restlichen Bilder in einem anderen.
    """
    found: list[Tag] = []
    seen: set[int] = set()
    for selector in selectors:
        try:
            matches = node.select(selector)
        except Exception:
            continue
        for match in matches:
            if id(match) not in seen:
                seen.add(id(match))
                found.append(match)
    return found


def is_usable_image(url: str, cfg: SiteConfig) -> bool:
    if not url or url.startswith("data:"):
        return False
    lowered = url.lower()
    return not any(token in lowered for token in cfg.image_url_deny)


def image_urls(node: Tag | BeautifulSoup, cfg: SiteConfig) -> list[str]:
    urls: list[str] = []
    for img in select_union(node, cfg.detail_selectors["images"]):
        for attr in cfg.image_url_attrs:
            url = _first_url_from_attr(img.get(attr))
            if not url:
                continue
            if not is_usable_image(url, cfg):
                # Platzhalter/Icon - naechstes Attribut desselben Bildes probieren.
                continue
            absolute = cfg.absolute(url)
            if absolute not in urls:
                urls.append(absolute)
            break
    return urls


# --------------------------------------------------------------------------
# Ergebnisse
# --------------------------------------------------------------------------


@dataclass
class ListingStub:
    """Ein Treffer aus der Ergebnisliste - reicht fuer die Dedup-Pruefung."""

    url: str
    title: str = ""
    price: int | None = None
    location: str = ""


@dataclass
class ListingDetail:
    url: str
    title: str = ""
    description: str = ""
    price: int | None = None
    year: int | None = None
    km: int | None = None
    model: str | None = None
    location: str = ""
    image_urls: list[str] = field(default_factory=list)


def parse_search_page(html: str, cfg: SiteConfig) -> list[ListingStub]:
    soup = BeautifulSoup(html, "lxml")
    stubs: list[ListingStub] = []
    seen: set[str] = set()
    for item in select_all(soup, cfg.list_selectors.get("item", [])):
        link = select_one(item, cfg.list_selectors.get("link", []))
        href = link.get("href") if link else None
        if not href:
            continue
        url = cfg.normalize(_first_url_from_attr(href))
        if not url:
            continue
        if url in seen:
            continue
        seen.add(url)
        stubs.append(
            ListingStub(
                url=url,
                title=text_of(item, cfg.list_selectors.get("title", []))
                or clean_text(link.get_text(" ", strip=True)),
                price=parse_number(text_of(item, cfg.list_selectors.get("price", []))),
                location=text_of(item, cfg.list_selectors.get("location", [])),
            )
        )
    return stubs


def _parse_attributes(soup: BeautifulSoup, cfg: SiteConfig) -> dict[str, str]:
    """Liest die Attribut-Tabelle ('Kilometerstand: 12.000 km') als Label->Wert."""
    attributes: dict[str, str] = {}
    for container in select_all(soup, cfg.detail_selectors["attr_container"]):
        full = clean_text(container.get_text(" ", strip=True))
        if not full:
            continue
        value_node = select_one(container, cfg.detail_selectors["attr_label"])
        if value_node is not None:
            value = clean_text(value_node.get_text(" ", strip=True))
            label = clean_text(full.replace(value, "", 1)) or full
        elif ":" in full:
            label, value = (clean_text(p) for p in full.split(":", 1))
        else:
            parts = full.split()
            label, value = " ".join(parts[:-1]), parts[-1]
        if label:
            attributes[label.rstrip(":").lower()] = value
    return attributes


def _lookup(attributes: dict[str, str], keys: list[str]) -> str | None:
    for key in keys:
        for label, value in attributes.items():
            if key in label:
                return value
    return None


def parse_detail_page(html: str, url: str, cfg: SiteConfig) -> ListingDetail:
    soup = BeautifulSoup(html, "lxml")
    attributes = _parse_attributes(soup, cfg)

    detail = ListingDetail(
        url=url,
        title=text_of(soup, cfg.detail_selectors["title"]),
        description=text_of(soup, cfg.detail_selectors["description"]),
        price=parse_number(text_of(soup, cfg.detail_selectors["price"])),
        location=text_of(soup, cfg.detail_selectors["location"]),
        image_urls=image_urls(soup, cfg),
    )
    detail.km = parse_number(_lookup(attributes, cfg.attribute_map.get("km", [])))
    detail.year = parse_year(_lookup(attributes, cfg.attribute_map.get("year", [])))
    detail.model = _lookup(attributes, cfg.attribute_map.get("model", [])) or None

    # Fallback: viele Inserate nennen Baujahr/km nur im Freitext.
    if detail.year is None:
        match = re.search(
            r"(?:Baujahr|EZ|Erstzulassung)\D{0,12}((?:19|20)\d{2})", detail.description, re.I
        )
        detail.year = int(match.group(1)) if match else None
    if detail.km is None:
        match = re.search(r"(\d[\d.\s']{2,})\s*(?:km|Kilometer)", detail.description, re.I)
        detail.km = parse_number(match.group(1)) if match else None
    return detail
