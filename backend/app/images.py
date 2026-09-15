"""Bild-Download, Thumbnail-Erzeugung und Loeschung (Stufe 5)."""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
from pathlib import Path

import httpx
from PIL import Image as PILImage

from app.config import settings
from app.scrapers.fetchers import USER_AGENT

log = logging.getLogger(__name__)

MAX_BYTES = 12 * 1024 * 1024


def _filename(listing_id: int, url: str, suffix: str = ".jpg") -> str:
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    return f"{listing_id}_{digest}{suffix}"


async def download_images(
    listing_id: int, urls: list[str], limit: int | None = None
) -> list[tuple[str, Path]]:
    """Laedt bis zu `limit` Bilder herunter. Gibt (Quell-URL, lokaler Pfad) zurueck."""
    limit = limit or settings.max_images_per_listing
    selected = urls[:limit]
    if not selected:
        return []

    results: list[tuple[str, Path]] = []
    async with httpx.AsyncClient(
        timeout=30.0, follow_redirects=True, headers={"User-Agent": USER_AGENT}
    ) as client:

        async def fetch(url: str) -> None:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                if len(resp.content) > MAX_BYTES:
                    log.warning("Bild zu gross, uebersprungen: %s", url)
                    return
                path = settings.image_dir / _filename(listing_id, url)
                # Re-Encode: normalisiert Format und begrenzt die Kantenlaenge,
                # damit das Vision-Modell nicht mit 4000px-Bildern arbeiten muss.
                with PILImage.open(io.BytesIO(resp.content)) as img:
                    img = img.convert("RGB")
                    img.thumbnail((1280, 1280))
                    img.save(path, "JPEG", quality=88)
                results.append((url, path))
            except Exception as exc:  # noqa: BLE001 - ein defektes Bild kippt kein Inserat
                log.warning("Bild-Download fehlgeschlagen (%s): %s", url, exc)

        await asyncio.gather(*(fetch(u) for u in selected))

    # Reihenfolge der Quelle beibehalten (erstes Bild = Hauptbild).
    order = {u: i for i, u in enumerate(selected)}
    return sorted(results, key=lambda r: order.get(r[0], 999))


def make_thumbnail(listing_id: int, source: Path) -> str | None:
    """Erzeugt das dauerhaft aufbewahrte Vorschaubild.

    Stufe 5 loescht alle Vollbilder; dieses eine kleine Bild bleibt, damit die
    Ergebnis-Ansicht auch nach der Loeschung noch eine Vorschau zeigen kann.
    """
    if not source.exists():
        return None
    target = settings.thumb_dir / f"{listing_id}.webp"
    try:
        with PILImage.open(source) as img:
            img = img.convert("RGB")
            img.thumbnail((settings.thumbnail_max_px, settings.thumbnail_max_px))
            img.save(target, "WEBP", quality=80, method=4)
    except Exception as exc:  # noqa: BLE001
        log.warning("Thumbnail fehlgeschlagen fuer Inserat %s: %s", listing_id, exc)
        return None
    return target.name


def delete_file(path: str | Path | None) -> bool:
    if not path:
        return False
    file = Path(path)
    try:
        file.unlink(missing_ok=True)
        return True
    except OSError as exc:
        log.warning("Konnte %s nicht loeschen: %s", file, exc)
        return False
