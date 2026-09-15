"""Laedt die zentrale Scraper-Konfiguration (sites.yaml)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import yaml

CONFIG_PATH = Path(__file__).with_name("sites.yaml")

# Query-Parameter, die nur die Herkunft/Position eines Treffers beschreiben.
# Sie muessen raus, bevor die URL als Dedup-Schluessel dient - sonst gilt
# dasselbe Inserat auf Listenplatz 3 als ein anderes als auf Platz 1.
TRACKING_PARAMS = {
    "pos",
    "ref",
    "referrer",
    "searchid",
    "action",
    "results",
    "lang",
    "fbclid",
    "gclid",
}

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _as_list(value: Any) -> list[str]:
    """Selektoren duerfen einzeln oder als Fallback-Liste notiert sein."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value]


def compact_url(template: str) -> str:
    """YAML-Folded-Scalars enthalten Umbrueche als Leerzeichen - hier entfernen."""
    return re.sub(r"\s+", "", template or "")


@dataclass(frozen=True)
class SiteConfig:
    key: str
    name: str
    enabled: bool
    base_url: str
    fetcher: str
    search_url_template: str
    pagination: dict[str, Any]
    wait_for: list[str]
    list_selectors: dict[str, list[str]]
    detail_selectors: dict[str, Any]
    attribute_map: dict[str, list[str]]
    prefilter_local: list[str]
    strip_params: list[str]
    image_url_attrs: list[str]
    image_url_deny: list[str]
    max_pages: int
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    def search_url(self, params: dict[str, Any], page: int = 1) -> str:
        """Baut die Such-URL inkl. Paginierung aus den Kriterien."""
        values = {k: "" if v is None else str(v) for k, v in params.items()}
        values.setdefault("page", str(page))

        template = self.search_url_template
        mode = (self.pagination or {}).get("mode")
        if page > 1 and mode == "path" and self.pagination.get("template"):
            template = compact_url(self.pagination["template"])
        url = _PLACEHOLDER.sub(lambda m: values.get(m.group(1), ""), template)
        if page > 1 and mode == "query":
            param = self.pagination.get("param", "page")
            url += ("&" if "?" in url else "?") + f"{param}={page}"
        return url

    def absolute(self, href: str) -> str:
        if not href:
            return ""
        if href.startswith("http://") or href.startswith("https://"):
            return href
        if href.startswith("//"):
            return "https:" + href
        return self.base_url.rstrip("/") + "/" + href.lstrip("/")

    def normalize(self, href: str) -> str:
        """Absolute, um Tracking-Parameter bereinigte URL - der Dedup-Schluessel."""
        url = self.absolute(href)
        if not url:
            return ""
        parts = urlsplit(url)
        drop = TRACKING_PARAMS | {p.lower() for p in self.strip_params}
        kept = [(k, v) for k, v in parse_qsl(parts.query) if k.lower() not in drop]
        return urlunsplit(
            (parts.scheme, parts.netloc, parts.path.rstrip("/") or "/", urlencode(kept), "")
        )


def _build(key: str, data: dict[str, Any], defaults: dict[str, Any]) -> SiteConfig:
    detail = data.get("detail") or {}
    attributes = detail.get("attributes") or {}
    return SiteConfig(
        key=key,
        name=data.get("name", key),
        enabled=bool(data.get("enabled", True)),
        base_url=compact_url(data.get("base_url", "")),
        fetcher=data.get("fetcher", "http"),
        search_url_template=compact_url(data.get("search_url_template", "")),
        pagination={
            **(data.get("pagination") or {}),
            **(
                {"template": compact_url((data.get("pagination") or {}).get("template", ""))}
                if (data.get("pagination") or {}).get("template")
                else {}
            ),
        },
        wait_for=_as_list(data.get("wait_for")),
        list_selectors={k: _as_list(v) for k, v in (data.get("list") or {}).items()},
        detail_selectors={
            "wait_for": _as_list(detail.get("wait_for")),
            "title": _as_list(detail.get("title")),
            "price": _as_list(detail.get("price")),
            "description": _as_list(detail.get("description")),
            "location": _as_list(detail.get("location")),
            "images": _as_list(detail.get("images")),
            "attr_container": _as_list(attributes.get("container")),
            "attr_label": _as_list(attributes.get("label")),
        },
        attribute_map={
            k: [s.lower() for s in _as_list(v)]
            for k, v in (detail.get("attribute_map") or {}).items()
        },
        prefilter_local=_as_list(data.get("prefilter_local")),
        strip_params=_as_list(data.get("strip_params")),
        image_url_attrs=_as_list(
            data.get("image_url_attrs") or defaults.get("image_url_attrs") or ["src"]
        ),
        image_url_deny=[
            token.lower()
            for token in _as_list(
                data.get("image_url_deny") or defaults.get("image_url_deny") or []
            )
        ],
        max_pages=int(data.get("max_pages") or defaults.get("max_pages") or 3),
        raw=data,
    )


def load_config(path: Path | None = None) -> dict[str, SiteConfig]:
    raw = yaml.safe_load((path or CONFIG_PATH).read_text(encoding="utf-8")) or {}
    defaults = raw.get("defaults") or {}
    return {key: _build(key, data, defaults) for key, data in (raw.get("sites") or {}).items()}


@lru_cache
def get_sites() -> dict[str, SiteConfig]:
    return load_config()


def reload_sites() -> dict[str, SiteConfig]:
    get_sites.cache_clear()
    return get_sites()
