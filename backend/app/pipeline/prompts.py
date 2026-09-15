"""Prompt-Bausteine der KI-Stufen.

Alle Prompts sind deutschsprachig, erzwingen JSON und enthalten die frei
konfigurierbaren Kriterien aus den Einstellungen - nichts ist hartkodiert.
"""

from __future__ import annotations

from typing import Any

# --------------------------------------------------------------------------
# Stufe 2 - Text-Analyse
# --------------------------------------------------------------------------

TEXT_SYSTEM = (
    "Du bist ein erfahrener Motorrad-Gutachter und pruefst Verkaufsinserate auf "
    "Hinweise zu Schaeden, Unfaellen und unserioesen Angeboten. Du antwortest "
    "ausschliesslich mit einem JSON-Objekt, ohne weiteren Text."
)


def text_prompt(listing: dict[str, Any], exclusions: str, criteria: dict[str, Any]) -> str:
    return f"""Pruefe das folgende Motorrad-Inserat.

AUSSCHLUSSKRITERIEN (fuehren zu einer Ablehnung, wenn der Text sie nahelegt):
{exclusions}

HARTE SUCHKRITERIEN (nur zur Einordnung, nicht erfinden):
- Budget bis {criteria.get('budget_max')} EUR
- Baujahr ab {criteria.get('year_min')}
- Laufleistung bis {criteria.get('km_max')} km

INSERAT
Titel: {listing.get('title') or '-'}
Preis: {listing.get('price') or '-'} EUR
Baujahr: {listing.get('year') or '-'}
Kilometerstand: {listing.get('km') or '-'} km
Ort: {listing.get('location') or '-'}
Beschreibung:
\"\"\"
{(listing.get('description') or '')[:6000]}
\"\"\"

Bewerte ausschliesslich den Zustand laut Text. Optik/Farbe ist hier NICHT relevant.
Wenn die Beschreibung zu duenn fuer ein Urteil ist, lehne nicht ab, sondern setze
eine niedrige confidence.

Antworte exakt in diesem JSON-Format:
{{
  "verdict": "ok" | "rejected",
  "confidence": 0.0-1.0,
  "findings": ["kurzer Befund", ...],
  "reasoning": "zwei bis drei Saetze Begruendung auf Deutsch"
}}"""


# --------------------------------------------------------------------------
# Stufe 3a - Vision (Bildbeschreibung)
# --------------------------------------------------------------------------

VISION_SYSTEM = (
    "Du beschreibst Fotos von Motorraedern sachlich und detailliert fuer eine "
    "spaetere automatische Auswertung. Du bewertest nicht, du beschreibst nur."
)

VISION_PROMPT = """Beschreibe dieses Motorrad-Foto praezise auf Deutsch.

Gehe auf folgende Punkte ein, soweit im Bild erkennbar:
- Farbe von Rahmen, Tank, Verkleidung und Felgen (jeweils einzeln benennen)
- Modell/Typ, falls erkennbar
- sichtbare Kratzer, Diebstahlspuren, Dellen, Rost, Schleifspuren an Hebeln,
  Lenkerenden, Fussrasten, Auspuff oder Verkleidung
- Anbauteile und Umbauten (Sturzpads, Koffer, Zubehoerauspuff, LED, Hoeckerabdeckung)
- Allgemeiner Pflegezustand und Bildqualitaet

Wenn etwas nicht erkennbar ist, schreibe das ausdruecklich. Erfinde nichts.
Antworte als Fliesstext, maximal 150 Woerter."""


# --------------------------------------------------------------------------
# Stufe 3b - Interpretation der Bildbeschreibungen
# --------------------------------------------------------------------------

INTERPRET_SYSTEM = (
    "Du gleichst Bildbeschreibungen eines Motorrads gegen die Optik-Wuensche "
    "eines Kaeufers ab. Du antwortest ausschliesslich mit einem JSON-Objekt."
)


def interpret_prompt(listing: dict[str, Any], descriptions: list[str], optical: str) -> str:
    joined = "\n\n".join(f"Bild {i + 1}: {d}" for i, d in enumerate(descriptions))
    return f"""OPTIK-KRITERIEN DES KAEUFERS:
{optical}

INSERAT: {listing.get('title') or '-'} ({listing.get('year') or '-'}, {listing.get('km') or '-'} km)

BILDBESCHREIBUNGEN:
{joined[:8000]}

Entscheide, ob das Motorrad die Optik-Kriterien erfuellt. Beziehe dich nur auf
das, was in den Beschreibungen tatsaechlich steht. Wenn ein Kriterium darin
nicht beurteilbar ist, werte es als unklar und senke die confidence, statt
abzulehnen.

Antworte exakt in diesem JSON-Format:
{{
  "verdict": "ok" | "rejected",
  "confidence": 0.0-1.0,
  "matched": ["erfuelltes Kriterium", ...],
  "violated": ["verletztes Kriterium", ...],
  "reasoning": "zwei bis drei Saetze Begruendung auf Deutsch"
}}"""


# --------------------------------------------------------------------------
# Stufe 6 - Ranking
# --------------------------------------------------------------------------

RANK_SYSTEM = (
    "Du bist ein Motorrad-Kaufberater und bringst vorgefilterte Angebote in eine "
    "Reihenfolge. Du antwortest ausschliesslich mit einem JSON-Objekt."
)

CLASS_FOCUS = {
    "passend": (
        "Diese Angebote haben Text- und Optik-Pruefung bestanden. Ranke nach "
        "Gesamtattraktivitaet: Preis-Leistung, Laufleistung, Baujahr, Zustand und "
        "wie sicher die Vorpruefung war."
    ),
    "unpassende_optik": (
        "Diese Angebote sind technisch in Ordnung, treffen aber die Optik-Wuensche "
        "nicht. Ranke danach, wie knapp die Optik verfehlt wurde und wie gut das "
        "Angebot sonst ist - oben steht, was sich am ehesten trotzdem lohnt."
    ),
    "unpassender_zustand": (
        "Diese Angebote wurden wegen Hinweisen auf Schaeden abgelehnt. Ranke "
        "danach, wie unsicher die Ablehnung war - oben steht, was am ehesten ein "
        "Fehlalarm sein koennte und eine manuelle Durchsicht verdient."
    ),
}


def rank_prompt(target_class: str, criteria: dict[str, Any], entries: list[dict[str, Any]]) -> str:
    modelle = ", ".join(criteria.get("models") or []) or "-"
    lines = []
    for entry in entries:
        eckdaten = (
            f"{entry.get('price') or '-'} EUR | baujahr: {entry.get('year') or '-'} "
            f"| km: {entry.get('km') or '-'}"
        )
        lines.append(
            f"""- id: {entry['id']}
  titel: {entry.get('title') or '-'}
  preis: {eckdaten}
  text_pruefung: {entry.get('text_summary') or '-'}
  optik_pruefung: {entry.get('optical_summary') or '-'}"""
        )
    return f"""KLASSE: {target_class}
{CLASS_FOCUS.get(target_class, '')}

SUCHKRITERIEN DES KAEUFERS:
Budget bis {criteria.get('budget_max')} EUR, Baujahr ab {criteria.get('year_min')},
maximal {criteria.get('km_max')} km, gesuchte Modelle: {modelle}

ANGEBOTE:
{chr(10).join(lines)[:12000]}

Vergib jedem Angebot einen score von 0 bis 100 (hoeher = besser) und eine kurze
Begruendung auf Deutsch. Bewerte jedes der genannten ids genau einmal.

Antworte exakt in diesem JSON-Format:
{{
  "rankings": [
    {{"id": <id>, "score": <0-100>, "reasoning": "ein bis zwei Saetze"}}
  ]
}}"""
