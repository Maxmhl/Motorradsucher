"""HTML-Beschaffung: Playwright fuer JS-lastige Seiten, httpx fuer statische.

Rate-Limiting ist bewusst konservativ (Abschnitt 8 des Plans): eine Pause je
Domain zwischen zwei Requests, dazu ein realistischer User-Agent.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections import defaultdict
from typing import Any

import httpx

from app.config import settings

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

BLOCK_MARKERS = (
    "captcha",
    "bot-schutz",
    "zugriff verweigert",
    "access denied",
    "are you a human",
    "ungewöhnliche aktivität",
)


class ScrapeError(RuntimeError):
    pass


class BlockedError(ScrapeError):
    """Seite hat mit Captcha/Bot-Schutz geantwortet."""


class RateLimiter:
    """Mindestabstand zwischen zwei Requests je Host, mit etwas Jitter."""

    def __init__(self, delay: float) -> None:
        self.delay = delay
        self._last: dict[str, float] = defaultdict(float)
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def wait(self, host: str) -> None:
        async with self._locks[host]:
            elapsed = time.monotonic() - self._last[host]
            pause = self.delay * random.uniform(0.8, 1.4) - elapsed
            if pause > 0:
                await asyncio.sleep(pause)
            self._last[host] = time.monotonic()


limiter = RateLimiter(settings.scrape_delay_seconds)


def _host(url: str) -> str:
    return url.split("//", 1)[-1].split("/", 1)[0]


def looks_blocked(html: str) -> bool:
    head = html[:4000].lower()
    return any(marker in head for marker in BLOCK_MARKERS)


class HttpFetcher:
    """Statische Seiten - schnell und ressourcenschonend."""

    async def __aenter__(self) -> HttpFetcher:
        self._client = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers={
                "User-Agent": USER_AGENT,
                "Accept-Language": "de-DE,de;q=0.9",
            },
        )
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self._client.aclose()

    async def get(self, url: str, wait_for: list[str] | None = None) -> str:
        await limiter.wait(_host(url))
        try:
            resp = await self._client.get(url)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (403, 429):
                raise BlockedError(
                    f"HTTP {exc.response.status_code} von {_host(url)} - vermutlich Bot-Schutz"
                ) from exc
            raise ScrapeError(f"HTTP {exc.response.status_code} fuer {url}") from exc
        except httpx.HTTPError as exc:
            raise ScrapeError(f"Abruf fehlgeschlagen fuer {url}: {exc}") from exc
        if looks_blocked(resp.text):
            raise BlockedError(f"Captcha/Bot-Schutz auf {url}")
        return resp.text

    async def get_bytes(self, url: str) -> bytes:
        await limiter.wait(_host(url))
        resp = await self._client.get(url)
        resp.raise_for_status()
        return resp.content


class PlaywrightFetcher:
    """JS-lastige Seiten (Kleinanzeigen, mobile.de)."""

    def __init__(self, headless: bool = True) -> None:
        self.headless = headless
        self._pw = None
        self._browser = None
        self._context = None

    async def __aenter__(self) -> PlaywrightFetcher:
        from playwright.async_api import async_playwright

        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=self.headless,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        self._context = await self._browser.new_context(
            user_agent=USER_AGENT,
            locale="de-DE",
            viewport={"width": 1440, "height": 900},
        )
        return self

    async def __aexit__(self, *exc: Any) -> None:
        for closer in (self._context, self._browser):
            if closer is not None:
                try:
                    await closer.close()
                except Exception:  # noqa: BLE001 - Aufraeumen darf nie werfen
                    log.debug("Fehler beim Schliessen des Browsers", exc_info=True)
        if self._pw is not None:
            await self._pw.stop()

    async def get(self, url: str, wait_for: list[str] | None = None) -> str:
        if self._context is None:
            raise ScrapeError("PlaywrightFetcher nicht initialisiert")
        await limiter.wait(_host(url))
        page = await self._context.new_page()
        try:
            response = await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            if response is not None and response.status in (403, 429):
                raise BlockedError(f"HTTP {response.status} von {_host(url)} - Bot-Schutz")
            for selector in wait_for or []:
                try:
                    await page.wait_for_selector(selector, timeout=8_000)
                    break
                except Exception:  # naechster Fallback-Selektor
                    continue
            # Lazy-Loading-Bilder nachladen lassen.
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(1200)
            html = await page.content()
        finally:
            await page.close()
        if looks_blocked(html):
            raise BlockedError(f"Captcha/Bot-Schutz auf {url}")
        return html


def fetcher_for(kind: str) -> HttpFetcher | PlaywrightFetcher:
    return PlaywrightFetcher() if kind == "playwright" else HttpFetcher()
