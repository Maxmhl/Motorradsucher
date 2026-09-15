# Motorrad-Sucher

Selbstgehostete Software, die Motorrad-Inserate von **Kleinanzeigen**, **mobile.de**
und **1000PS** automatisch durchsucht, per lokaler KI (Ollama) auf **Zustand** und
**Optik** vorfiltert und die besten Treffer in einer Web-Oberfläche präsentiert.

Läuft vollständig lokal — es verlässt kein Inserat und keine Bewertung den Server.

---

## Wie es funktioniert

```
┌─────────────┐   ┌──────────────┐   ┌───────────────┐   ┌────────────────┐   ┌───────────┐
│   Scraper   │──▶│  Text-Stage  │──▶│   Bild-Stage  │──▶│ Klassifizierung│──▶│  Ranking  │
│ (Playwright)│   │ (Ollama LLM) │   │ (Vision+LLM)  │   │    3 Klassen   │   │ (Ollama)  │
└─────────────┘   └──────────────┘   └───────────────┘   └────────────────┘   └───────────┘
       │                                                                             │
       ▼                                                                             ▼
   SQLite-DB ◀──────────────────────────────────────────────────────── Web-UI (React)
```

| Stufe | Was passiert |
|---|---|
| **1 Scraping** | Websiteseitige Filter grenzen vor (keine KI). Jeder Link wird gegen `listings.url` geprüft — nur wirklich neue Inserate werden geladen. Bereits analysierte Links bleiben dauerhaft gespeichert, auch wenn das Inserat offline geht. |
| **2 Text-Analyse** | Ein frei wählbares Textmodell prüft die Beschreibung auf Unfall-, Sturz- und Schadenshinweise. Ergebnis: `text_ok` oder `text_rejected` — abgelehnte Inserate werden **markiert, nicht gelöscht**. |
| **3 Bild-Analyse** | Ein Vision-Modell beschreibt jedes Bild in Textform. Ein zweites Textmodell gleicht die gesammelten Beschreibungen gegen deine Optik-Kriterien ab. Ergebnis: `optical_ok` oder `optical_rejected`. |
| **4 Klassifizierung** | Drei Klassen: *Passend*, *Unpassende Optik*, *Unpassender Zustand*. Bei Treffer in beiden Reject-Klassen gewinnt immer **unpassender Zustand**. |
| **5 Bilder löschen** | Die Vollbilder werden von der Platte gelöscht (`images.deleted_at` gesetzt). Die Bildbeschreibungen, der Link und ein kleines Vorschaubild bleiben dauerhaft erhalten. |
| **6 Ranking** | Ein frei wählbares Modell bewertet und sortiert innerhalb jeder Klasse und nutzt dabei die Konfidenz und Befunde aus Stufe 2/3. *Passend* zeigt alle Treffer, die beiden Reject-Klassen nur die Top 3 (Rest bleibt abrufbar). |

---

## Schnellstart mit Docker

Voraussetzung: **Ollama läuft auf dem Host** (wegen GPU-Zugriff), nicht im Container.

```bash
git clone <dieses-repo> Motorradsucher && cd Motorradsucher
cp .env.example .env          # OLLAMA_BASE_URL prüfen
docker compose up -d --build
```

Oberfläche: <http://localhost:8000> · API-Doku: <http://localhost:8000/docs>

Danach in **Einstellungen** je Pipeline-Stufe ein Modell wählen und auf
**Suche jetzt starten** (Dashboard) drücken.

---

## Entwicklung ohne Docker

```bash
# Backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
DATA_DIR=../data uvicorn app.main:app --reload     # http://localhost:8000

# Frontend (zweites Terminal) — Vite reicht /api und /ws ans Backend weiter
cd frontend
npm install
npm run dev                                         # http://localhost:5173
```

Tests und Linting:

```bash
cd backend && .venv/bin/pytest -q && .venv/bin/ruff check app tests
cd frontend && npm run lint && npm run build
```

---

## Modelle & die beiden V100

Modelle sind **nicht hartkodiert**. Das UI liest über `/api/tags` aus, was auf dem
Server installiert ist, und zeigt je Modell an, ob es auf eine Karte passt:

| Anzeige | Bedeutung |
|---|---|
| *passt auf eine V100* | ≤ ~13,6 GB — läuft auf einer Karte, höchster Durchsatz |
| *braucht Tensor-Split über beide Karten* | 14–27 GB — läuft, aber spürbar langsamer |
| *zu groß für 2× 16 GB* | passt nicht |

**Empfehlung für hohen Durchsatz:** zwei Ollama-Instanzen, eine pro Karte, und
Text- und Bild-Stufe getrennt darauf legen — statt ein großes Modell über beide
Karten zu splitten:

```bash
CUDA_VISIBLE_DEVICES=0 OLLAMA_HOST=127.0.0.1:11434 ollama serve   # Text/Interpretation/Ranking
CUDA_VISIBLE_DEVICES=1 OLLAMA_HOST=127.0.0.1:11435 ollama serve   # Vision
```

```env
OLLAMA_BASE_URL_TEXT=http://host.docker.internal:11434
OLLAMA_BASE_URL_VISION=http://host.docker.internal:11435
```

Bewährte Größenordnung (≤ 14B, Q4/Q5):

```bash
ollama pull qwen2.5:14b-instruct-q4_K_M   # Text, Interpretation, Ranking
ollama pull qwen2.5vl:7b                  # Bild-Beschreibung (multimodal)
```

Fehlt für eine Stufe ein Modell, wird sie **übersprungen statt geraten** — die
Inserate gelten dann für diese Stufe als unauffällig und das Dashboard weist darauf hin.

---

## Scraper-Selektoren pflegen

Website-Layouts ändern sich. Alle Selektoren und URL-Vorlagen stehen deshalb
zentral in **`backend/app/scrapers/sites.yaml`**, nicht im Code. Jeder Selektor
darf eine Liste sein — der erste Treffer gewinnt, die übrigen sind Fallbacks.

Nach einer Layout-Änderung:

```bash
# Prüfen, was noch greift
cd backend
.venv/bin/python -m app.scrapers.check --site kleinanzeigen
.venv/bin/python -m app.scrapers.check --site tausendps --detail --url "https://www.1000ps.de/..."

# Gegen eine gespeicherte HTML-Datei, wenn die Seite blockt
.venv/bin/python -m app.scrapers.check --site mobile_de --file gespeichert.html
```

`sites.yaml` ist in Compose als Volume eingebunden — nach dem Bearbeiten genügt
in den Einstellungen **„sites.yaml neu laden"**, kein Neustart nötig.

> **Stand der Selektoren:** Die 1000PS-Selektoren sind gegen die echte Seite
> verifiziert (Trefferliste und Detailseite). Kleinanzeigen und mobile.de sind
> als sorgfältige Vorbelegung hinterlegt, konnten aber nicht live geprüft werden —
> bitte beim ersten Lauf mit `app.scrapers.check` gegenprüfen. Greift ein Selektor
> nicht, sagt das Log genau, welcher YAML-Schlüssel zu korrigieren ist.

### Rechtliches und Fairness

Scraping von Kleinanzeigen und mobile.de sollte moderat erfolgen. Eingebaut sind
ein Mindestabstand je Domain (`SCRAPE_DELAY_SECONDS`, Standard 2,5 s, mit Jitter),
ein realistischer User-Agent und eine Erkennung von Captcha- und Bot-Schutz-Seiten,
die den Abruf für die betroffene Seite abbricht statt weiterzuhämmern. Die
Nutzungsbedingungen der Portale gelten unabhängig davon — das Tempo bitte nicht
ohne Not hochdrehen.

---

## Bilder und Speicherplatz

Der Plan sieht vor, Bilder nach der Analyse zu löschen — die Ergebnis-Ansicht soll
aber eine Vorschau zeigen. Aufgelöst wird das so:

* Während der Analyse liegen bis zu `MAX_IMAGES_PER_LISTING` Vollbilder in `data/images/`.
* **Beim Download** entsteht je Inserat **ein Vorschaubild** (WebP, max. 480 px) in
  `data/thumbs/` — bewusst schon dort und nicht erst in Stufe 3, weil textlich
  abgelehnte Inserate die Bild-Stufe nie durchlaufen, in der Klasse *Unpassender
  Zustand* aber trotzdem mit Vorschau erscheinen sollen.
* Stufe 5 löscht alle Vollbilder. Übrig bleiben pro Inserat ~10–30 KB.

Abschaltbar über *Einstellungen → Vorschaubild behalten*.

---

## Konfiguration

Alles in `.env` (Vorlage: `.env.example`):

| Variable | Bedeutung |
|---|---|
| `OLLAMA_BASE_URL` | Ollama-Adresse (Standard für alle Stufen) |
| `OLLAMA_BASE_URL_TEXT` / `_VISION` | eigene Instanz je Stufe, um die GPUs zu trennen |
| `DATA_DIR` | Ablage für DB, Bilder und Thumbnails |
| `TEXT_CONCURRENCY` / `VISION_CONCURRENCY` | parallele Inserate je Stufe |
| `MAX_IMAGES_PER_LISTING` | Bilder je Inserat, die das Vision-Modell sieht |
| `SCRAPE_DELAY_SECONDS` | Mindestabstand zwischen zwei Requests je Domain |
| `SCHEDULER_TIMEZONE` | Zeitzone für den Cron-Zeitplan |

Suchkriterien, Freitext-Kriterien, Modellauswahl und Zeitplan werden **im UI**
gepflegt und in der Tabelle `settings` gespeichert.

---

## Projektstruktur

```
backend/
  app/
    main.py              FastAPI-App, liefert auch das gebaute Frontend aus
    models.py            SQLAlchemy: sites, listings, images, runs, logs, settings
    ollama.py            Ollama-Client, Modell-Liste inkl. VRAM-Einschätzung
    images.py            Download, Thumbnail, Löschung
    scheduler.py         Cron-Zeitplan für automatische Runs
    scrapers/
      sites.yaml         ALLE Selektoren und URL-Vorlagen
      check.py           Selektor-Prüfung (CLI)
      fetchers.py        Playwright / httpx, Rate-Limiting, Bot-Schutz-Erkennung
      parser.py          HTML → strukturierte Daten (netzwerkfrei, testbar)
    pipeline/
      runner.py          orchestriert die sechs Stufen
      stage_*.py         je eine Datei pro Stufe
      prompts.py         alle Prompts an einer Stelle
    api/                 REST-Endpunkte und WebSocket
  tests/                 60 Tests, inkl. End-to-End-Lauf gegen HTML-Fixtures
frontend/
  src/pages/             Dashboard, Ergebnisse, Einstellungen, Logs
```

## Datenbank

SQLite im WAL-Modus unter `data/motorradsucher.db`. Sichern heißt: Datei kopieren.

```bash
sqlite3 data/motorradsucher.db ".backup data/backup.db"
```

Das Schema wird beim Start automatisch angelegt.
