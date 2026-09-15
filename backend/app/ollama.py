"""Client fuer die lokale Ollama-HTTP-API.

Modelle werden bewusst nicht hartkodiert: `list_models()` liest ueber /api/tags
aus, was auf dem Server installiert ist, und schaetzt dazu den VRAM-Bedarf, damit
das UI anzeigen kann, ob ein Modell auf eine einzelne V100 (16 GB) passt.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from pathlib import Path
from typing import Any

import httpx

from app.config import settings

log = logging.getLogger(__name__)

# Nutzbares VRAM je V100: 16 GB abzueglich Reserve fuer KV-Cache/Kontext.
SINGLE_GPU_VRAM_BYTES = 16 * 1024**3
USABLE_FRACTION = 0.85


class OllamaError(RuntimeError):
    pass


def _fmt_gb(num_bytes: int | None) -> float | None:
    if not num_bytes:
        return None
    return round(num_bytes / 1024**3, 2)


def classify_fit(size_bytes: int | None) -> str:
    """'single_gpu' | 'tensor_split' | 'too_large' | 'unknown'."""
    if not size_bytes:
        return "unknown"
    usable = SINGLE_GPU_VRAM_BYTES * USABLE_FRACTION
    if size_bytes <= usable:
        return "single_gpu"
    if size_bytes <= usable * 2:
        return "tensor_split"
    return "too_large"


def extract_json(raw: str) -> dict[str, Any]:
    """Robuste JSON-Extraktion - Modelle verpacken Antworten gern in Prosa/Fences."""
    if not raw:
        raise OllamaError("Leere Modellantwort")
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise OllamaError(f"Keine JSON-Struktur in Modellantwort: {raw[:200]!r}") from None
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise OllamaError(f"Ungueltiges JSON in Modellantwort: {raw[:200]!r}") from exc
    if not isinstance(parsed, dict):
        raise OllamaError("Modellantwort ist kein JSON-Objekt")
    return parsed


class OllamaClient:
    def __init__(self, base_url: str | None = None, timeout: float | None = None) -> None:
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.timeout = timeout or settings.ollama_timeout_seconds

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.post(f"{self.base_url}{path}", json=payload)
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise OllamaError(
                    f"Ollama {path} -> HTTP {exc.response.status_code}: {exc.response.text[:200]}"
                ) from exc
            except httpx.HTTPError as exc:
                raise OllamaError(f"Ollama nicht erreichbar ({self.base_url}): {exc}") from exc
            return resp.json()

    async def list_models(self) -> list[dict[str, Any]]:
        """Installierte Modelle inkl. VRAM-Einschaetzung."""
        async with httpx.AsyncClient(timeout=20.0) as client:
            try:
                resp = await client.get(f"{self.base_url}/api/tags")
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                raise OllamaError(f"Ollama nicht erreichbar ({self.base_url}): {exc}") from exc
        models = []
        for entry in resp.json().get("models", []):
            size = entry.get("size")
            details = entry.get("details") or {}
            models.append(
                {
                    "name": entry.get("name"),
                    "size_bytes": size,
                    "size_gb": _fmt_gb(size),
                    "parameter_size": details.get("parameter_size"),
                    "quantization": details.get("quantization_level"),
                    "family": details.get("family"),
                    "families": details.get("families") or [],
                    "fit": classify_fit(size),
                    # Heuristik: multimodale Modelle melden eine Vision-Familie mit.
                    "vision_capable": any(
                        "clip" in f.lower() or "vision" in f.lower() or "mllama" in f.lower()
                        for f in (details.get("families") or [])
                    ),
                }
            )
        return sorted(models, key=lambda m: m["name"] or "")

    async def health(self) -> dict[str, Any]:
        try:
            models = await self.list_models()
        except OllamaError as exc:
            return {"url": self.base_url, "reachable": False, "error": str(exc), "models": 0}
        return {"url": self.base_url, "reachable": True, "error": None, "models": len(models)}

    async def generate_json(
        self,
        model: str,
        prompt: str,
        *,
        system: str | None = None,
        images: list[Path] | None = None,
        temperature: float = 0.1,
        num_ctx: int | None = None,
    ) -> dict[str, Any]:
        """Ein Aufruf mit erzwungenem JSON-Format."""
        raw = await self.generate_text(
            model,
            prompt,
            system=system,
            images=images,
            temperature=temperature,
            num_ctx=num_ctx,
            fmt="json",
        )
        return extract_json(raw)

    async def generate_text(
        self,
        model: str,
        prompt: str,
        *,
        system: str | None = None,
        images: list[Path] | None = None,
        temperature: float = 0.2,
        num_ctx: int | None = None,
        fmt: str | None = None,
    ) -> str:
        if not model:
            raise OllamaError("Kein Modell gewaehlt")
        options: dict[str, Any] = {"temperature": temperature}
        if num_ctx:
            options["num_ctx"] = num_ctx
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": options,
        }
        if system:
            payload["system"] = system
        if fmt:
            payload["format"] = fmt
        if images:
            payload["images"] = [
                base64.b64encode(p.read_bytes()).decode("ascii") for p in images if p.exists()
            ]
        data = await self._post("/api/generate", payload)
        return (data.get("response") or "").strip()


def client_for(stage: str, settings_values: dict[str, Any] | None = None) -> OllamaClient:
    """Client fuer eine Pipeline-Stage - respektiert getrennte Instanzen je GPU.

    Die Ollama-Adresse(n) koennen im UI (Tabelle `settings`) hinterlegt werden;
    das hat Vorrang vor der .env-Konfiguration. Ist im UI nichts gesetzt,
    greift der gewohnte Fallback aus `app.config.settings`.
    """
    values = settings_values or {}
    base = (values.get("ollama_base_url") or "").strip()
    text_url = (values.get("ollama_base_url_text") or "").strip()
    vision_url = (values.get("ollama_base_url_vision") or "").strip()

    if stage in ("text", "interpretation", "ranking") and text_url:
        return OllamaClient(text_url)
    if stage == "vision" and vision_url:
        return OllamaClient(vision_url)
    if base:
        return OllamaClient(base)
    return OllamaClient(settings.ollama_url_for(stage))
