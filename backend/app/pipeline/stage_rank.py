"""Stufe 6 - Ranking innerhalb jeder der drei Klassen.

Genutzt wird der Kontext aus Stufe 2/3 (Konfidenz, konkrete Auffaelligkeiten).
Fuer Klasse "passend" werden alle Treffer gerankt, fuer die beiden
Reject-Klassen entscheidet das Ranking, welche Top-N im UI sichtbar sind -
der Rest bleibt in der DB abrufbar, aber ausgeblendet.
"""

from __future__ import annotations

from sqlalchemy import select

from app.db import session_scope
from app.models import FinalClass, Listing
from app.ollama import OllamaError, client_for
from app.pipeline.context import RunContext
from app.pipeline.prompts import RANK_SYSTEM, rank_prompt

BATCH_SIZE = 12


def _summary(verdict: dict | None, reasoning: str | None) -> str:
    if not verdict:
        return reasoning or "-"
    confidence = verdict.get("confidence")
    parts = [f"{verdict.get('verdict', '?')}"]
    if confidence is not None:
        parts.append(f"confidence {confidence}")
    findings = verdict.get("findings") or verdict.get("violated") or []
    if findings:
        parts.append("Auffälligkeiten: " + ", ".join(str(f) for f in findings[:4]))
    if reasoning:
        parts.append(reasoning[:300])
    return " | ".join(parts)


def _fallback_score(listing: Listing) -> float:
    """Heuristik, wenn kein Ranking-Modell gewaehlt oder erreichbar ist.

    Guenstiger, neuer und laufleistungsaermer ist besser; die Konfidenz der
    Vorpruefung geht mit ein.
    """
    score = 50.0
    if listing.price:
        score += max(-20.0, min(20.0, (5000 - listing.price) / 150))
    if listing.year:
        score += max(-10.0, min(15.0, (listing.year - 2018) * 3))
    if listing.km is not None:
        score += max(-15.0, min(15.0, (30000 - listing.km) / 2000))
    for verdict in (listing.text_verdict, listing.optical_verdict):
        if verdict and isinstance(verdict.get("confidence"), (int, float)):
            confidence = float(verdict["confidence"])
            score += confidence * 5 if str(verdict.get("verdict")) == "ok" else -confidence * 5
    return round(max(0.0, min(100.0, score)), 1)


async def _rank_class(
    ctx: RunContext, target_class: str, listing_ids: list[int], model: str
) -> None:
    if not listing_ids:
        return
    criteria = ctx.settings.get("criteria") or {}

    async with session_scope() as session:
        listings = (
            await session.execute(select(Listing).where(Listing.id.in_(listing_ids)))
        ).scalars().all()
        entries = [
            {
                "id": listing.id,
                "title": listing.title,
                "price": listing.price,
                "year": listing.year,
                "km": listing.km,
                "text_summary": _summary(listing.text_verdict, listing.text_reasoning),
                "optical_summary": _summary(listing.optical_verdict, listing.optical_reasoning),
            }
            for listing in listings
        ]

    scores: dict[int, tuple[float, str]] = {}
    if model:
        client = client_for("ranking", ctx.settings)
        for start in range(0, len(entries), BATCH_SIZE):
            ctx.raise_if_cancelled()
            batch = entries[start : start + BATCH_SIZE]
            try:
                result = await client.generate_json(
                    model, rank_prompt(target_class, criteria, batch), system=RANK_SYSTEM
                )
            except OllamaError as exc:
                await ctx.log(
                    f"Ranking-Modell-Fehler ({target_class}): {exc} - nutze Heuristik",
                    level="warning",
                )
                continue
            for item in result.get("rankings") or []:
                try:
                    listing_id = int(item["id"])
                    score = float(item.get("score", 0))
                except (KeyError, TypeError, ValueError):
                    continue
                scores[listing_id] = (
                    max(0.0, min(100.0, score)),
                    str(item.get("reasoning") or ""),
                )

    async with session_scope() as session:
        listings = (
            await session.execute(select(Listing).where(Listing.id.in_(listing_ids)))
        ).scalars().all()
        for listing in listings:
            if listing.id in scores:
                listing.rank_score, listing.rank_reasoning = scores[listing.id]
            else:
                listing.rank_score = _fallback_score(listing)
                listing.rank_reasoning = listing.rank_reasoning or (
                    "Automatisch bewertet (kein Ranking-Modell verfügbar): "
                    "Preis, Baujahr, Laufleistung und Konfidenz der Vorprüfung."
                )
        # Position je Klasse vergeben - das UI blendet damit die Top-N ein.
        for position, listing in enumerate(
            sorted(listings, key=lambda ls: ls.rank_score or 0, reverse=True), start=1
        ):
            listing.rank_position = position

    await ctx.advance("rank", count=len(listing_ids))


async def run_stage(ctx: RunContext, buckets: dict[str, list[int]]) -> None:
    model = (ctx.settings.get("ranking_model") or "").strip()
    total = sum(len(v) for v in buckets.values())
    await ctx.start_stage("rank", total=total)
    if not model:
        await ctx.log(
            "Kein Ranking-Modell gewählt - es wird nach Preis, Baujahr, km und "
            "Konfidenz der Vorprüfung sortiert",
            level="warning",
        )
    for target_class in (
        FinalClass.passend.value,
        FinalClass.unpassende_optik.value,
        FinalClass.unpassender_zustand.value,
    ):
        await _rank_class(ctx, target_class, buckets.get(target_class, []), model)

    top_n = int(ctx.settings.get("top_n_rejected") or 3)
    await ctx.finish_stage("rank", model=model or "heuristik", top_n_rejected=top_n)
    await ctx.log(f"Ranking abgeschlossen ({total} Inserate)")
