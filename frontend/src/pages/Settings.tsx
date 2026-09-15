import { useEffect, useState } from 'react'

import {
  api,
  type AppSettings,
  type ModelsResponse,
  type OllamaModel,
  type Site,
} from '../lib/api'

const FIT_LABEL: Record<OllamaModel['fit'], string> = {
  single_gpu: 'passt auf eine V100',
  tensor_split: 'braucht Tensor-Split über beide Karten',
  too_large: 'zu groß für 2× 16 GB',
  unknown: 'Größe unbekannt',
}

const FIT_STYLE: Record<OllamaModel['fit'], string> = {
  single_gpu: 'bg-emerald-950 text-emerald-300',
  tensor_split: 'bg-amber-950 text-amber-300',
  too_large: 'bg-rose-950 text-rose-300',
  unknown: 'bg-ink-700 text-slate-400',
}

const STAGE_FIELDS: {
  key: 'text_model' | 'vision_model' | 'interpretation_model' | 'ranking_model'
  stage: string
  label: string
  hint: string
  visionOnly?: boolean
}[] = [
  {
    key: 'text_model',
    stage: 'text',
    label: 'Text-Analyse (Stufe 2)',
    hint: 'Prüft die Beschreibung auf Unfall-, Sturz- und Schadenshinweise.',
  },
  {
    key: 'vision_model',
    stage: 'vision',
    label: 'Bild-Beschreibung (Stufe 3a)',
    hint: 'Multimodales Modell, beschreibt jedes Bild in Textform.',
    visionOnly: true,
  },
  {
    key: 'interpretation_model',
    stage: 'interpretation',
    label: 'Bild-Interpretation (Stufe 3b)',
    hint: 'Gleicht die Bildbeschreibungen gegen deine Optik-Kriterien ab.',
  },
  {
    key: 'ranking_model',
    stage: 'ranking',
    label: 'Ranking (Stufe 6)',
    hint: 'Bewertet und sortiert innerhalb jeder der drei Klassen.',
  },
]

function ModelSelect({
  value,
  models,
  visionOnly,
  onChange,
}: {
  value: string
  models: OllamaModel[]
  visionOnly?: boolean
  onChange: (value: string) => void
}) {
  const options = visionOnly ? models.filter((model) => model.vision_capable) : models
  const selected = models.find((model) => model.name === value)

  return (
    <div>
      <select className="field" value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">— Stufe überspringen —</option>
        {options.map((model) => (
          <option key={model.name} value={model.name}>
            {model.name}
            {model.parameter_size ? ` · ${model.parameter_size}` : ''}
            {model.size_gb ? ` · ${model.size_gb} GB` : ''}
          </option>
        ))}
        {/* Gespeichertes Modell anzeigen, auch wenn Ollama gerade nicht antwortet. */}
        {value && !models.some((model) => model.name === value) && (
          <option value={value}>{value} (nicht installiert?)</option>
        )}
      </select>
      {selected && (
        <p className="mt-1.5">
          <span className={`chip ${FIT_STYLE[selected.fit]}`}>{FIT_LABEL[selected.fit]}</span>
        </p>
      )}
      {visionOnly && options.length === 0 && (
        <p className="mt-1.5 text-xs text-amber-400">
          Kein multimodales Modell gefunden — z. B. <code>ollama pull qwen2.5vl:7b</code>
        </p>
      )}
    </div>
  )
}

export default function Settings() {
  const [settings, setSettings] = useState<AppSettings | null>(null)
  const [models, setModels] = useState<ModelsResponse | null>(null)
  const [sites, setSites] = useState<Site[]>([])
  const [status, setStatus] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState<string | null>(null)

  useEffect(() => {
    void (async () => {
      try {
        const [loadedSettings, loadedModels, loadedSites] = await Promise.all([
          api.settings(),
          api.models(),
          api.sites(),
        ])
        setSettings(loadedSettings)
        setModels(loadedModels)
        setSites(loadedSites)
      } catch (exc) {
        setError(exc instanceof Error ? exc.message : String(exc))
      }
    })()
  }, [])

  if (!settings) {
    return <p className="text-sm text-slate-500">{error ?? 'lädt …'}</p>
  }

  const update = <K extends keyof AppSettings>(key: K, value: AppSettings[K]) =>
    setSettings((prev) => (prev ? { ...prev, [key]: value } : prev))

  const updateCriteria = <K extends keyof AppSettings['criteria']>(
    key: K,
    value: AppSettings['criteria'][K],
  ) =>
    setSettings((prev) =>
      prev ? { ...prev, criteria: { ...prev.criteria, [key]: value } } : prev,
    )

  const save = async () => {
    setSaving(true)
    setStatus(null)
    setError(null)
    try {
      const result = await api.saveSettings(settings)
      setSettings(result.settings)
      if (result.schedule?.error) {
        setError(`Zeitplan nicht aktiv: ${result.schedule.error}`)
      } else if (result.schedule?.next_run) {
        setStatus(`Gespeichert. Nächster Run: ${new Date(result.schedule.next_run).toLocaleString('de-DE')}`)
      } else {
        setStatus('Gespeichert.')
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc))
    } finally {
      setSaving(false)
    }
  }

  const testModel = async (model: string, stage: string) => {
    if (!model) return
    setTesting(stage)
    setStatus(null)
    setError(null)
    try {
      const result = await api.testModel(model, stage)
      if (result.ok) setStatus(`${model} antwortet: „${result.response?.trim()}“`)
      else setError(`${model}: ${result.error}`)
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc))
    } finally {
      setTesting(null)
    }
  }

  return (
    <div className="space-y-6 pb-20">
      {status && (
        <div className="card border-emerald-900/70 bg-emerald-950/30 px-4 py-3 text-sm text-emerald-200">
          {status}
        </div>
      )}
      {error && (
        <div className="card border-rose-900/70 bg-rose-950/40 px-4 py-3 text-sm text-rose-200">
          {error}
        </div>
      )}

      <section className="card p-5">
        <h2 className="text-sm font-semibold text-slate-200">Modellauswahl je Pipeline-Stufe</h2>
        <p className="mt-1 text-xs text-slate-500">
          Gelistet wird, was auf dem Server installiert ist (Ollama <code>/api/tags</code>).
          {models?.endpoints.map((endpoint) => (
            <span key={endpoint.url} className="ml-2">
              {endpoint.url} ({endpoint.stages}):{' '}
              {endpoint.reachable ? `${endpoint.count} Modelle` : 'nicht erreichbar'}
            </span>
          ))}
        </p>

        <div className="mt-4 grid gap-5 lg:grid-cols-2">
          {STAGE_FIELDS.map((field) => (
            <div key={field.key}>
              <label className="label">{field.label}</label>
              <ModelSelect
                value={settings[field.key]}
                models={models?.models ?? []}
                visionOnly={field.visionOnly}
                onChange={(value) => update(field.key, value)}
              />
              <div className="mt-1.5 flex items-center justify-between gap-2">
                <p className="text-xs text-slate-500">{field.hint}</p>
                <button
                  className="btn-ghost shrink-0 !px-2 !py-1 text-xs"
                  disabled={!settings[field.key] || testing === field.stage}
                  onClick={() => void testModel(settings[field.key], field.stage)}
                >
                  {testing === field.stage ? 'testet …' : 'Testcall'}
                </button>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="card p-5">
        <h2 className="text-sm font-semibold text-slate-200">Suchkriterien</h2>
        <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <label className="label" htmlFor="budget">Budget (€)</label>
            <input
              id="budget"
              type="number"
              className="field"
              value={settings.criteria.budget_max}
              onChange={(event) => updateCriteria('budget_max', Number(event.target.value))}
            />
          </div>
          <div>
            <label className="label" htmlFor="year">Baujahr ab</label>
            <input
              id="year"
              type="number"
              className="field"
              value={settings.criteria.year_min}
              onChange={(event) => updateCriteria('year_min', Number(event.target.value))}
            />
          </div>
          <div>
            <label className="label" htmlFor="kmmax">Laufleistung bis (km)</label>
            <input
              id="kmmax"
              type="number"
              className="field"
              value={settings.criteria.km_max}
              onChange={(event) => updateCriteria('km_max', Number(event.target.value))}
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label" htmlFor="zip">PLZ</label>
              <input
                id="zip"
                className="field"
                value={settings.criteria.zip_code}
                onChange={(event) => updateCriteria('zip_code', event.target.value)}
              />
            </div>
            <div>
              <label className="label" htmlFor="radius">Umkreis (km)</label>
              <input
                id="radius"
                type="number"
                className="field"
                value={settings.criteria.radius_km}
                onChange={(event) => updateCriteria('radius_km', Number(event.target.value))}
              />
            </div>
          </div>
        </div>
        <div className="mt-4">
          <label className="label" htmlFor="models">Gesuchte Modelle (eines pro Zeile)</label>
          <textarea
            id="models"
            className="field h-28 font-mono text-xs"
            value={settings.criteria.models.join('\n')}
            onChange={(event) =>
              updateCriteria(
                'models',
                event.target.value.split('\n').map((line) => line.trim()).filter(Boolean),
              )
            }
          />
          <p className="mt-1 text-xs text-slate-500">
            Jede Zeile wird als eigene Suchanfrage an jede Seite geschickt.
          </p>
        </div>
      </section>

      <section className="card p-5">
        <h2 className="text-sm font-semibold text-slate-200">Freitext-Kriterien für die KI</h2>
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <div>
            <label className="label" htmlFor="exclusions">Ausschlusskriterien Text (Stufe 2)</label>
            <textarea
              id="exclusions"
              className="field h-32"
              value={settings.text_exclusions}
              onChange={(event) => update('text_exclusions', event.target.value)}
            />
            <p className="mt-1 text-xs text-slate-500">
              z. B. „Unfall, Sturz, Rahmenschaden“ — wird wörtlich in den Prompt übernommen.
            </p>
          </div>
          <div>
            <label className="label" htmlFor="optical">Optik-Kriterien (Stufe 3)</label>
            <textarea
              id="optical"
              className="field h-32"
              value={settings.optical_criteria}
              onChange={(event) => update('optical_criteria', event.target.value)}
            />
            <p className="mt-1 text-xs text-slate-500">
              z. B. „blauer Rahmen mit blauen Felgen“.
            </p>
          </div>
        </div>
      </section>

      <section className="card p-5">
        <h2 className="text-sm font-semibold text-slate-200">Runs & Zeitplan</h2>
        <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <label className="label" htmlFor="topn">Sichtbare Treffer je Reject-Klasse</label>
            <input
              id="topn"
              type="number"
              min={0}
              className="field"
              value={settings.top_n_rejected}
              onChange={(event) => update('top_n_rejected', Number(event.target.value))}
            />
          </div>
          <div>
            <label className="label" htmlFor="maxlistings">Neue Inserate je Run</label>
            <input
              id="maxlistings"
              type="number"
              min={1}
              className="field"
              value={settings.max_listings_per_run}
              onChange={(event) => update('max_listings_per_run', Number(event.target.value))}
            />
          </div>
          <div>
            <label className="label" htmlFor="cron">Zeitplan (Cron)</label>
            <input
              id="cron"
              className="field font-mono"
              value={settings.schedule_cron}
              onChange={(event) => update('schedule_cron', event.target.value)}
              placeholder="0 7 * * *"
            />
            <p className="mt-1 text-xs text-slate-500">Minute Stunde Tag Monat Wochentag</p>
          </div>
          <div className="space-y-3 pt-6">
            <label className="flex items-center gap-2 text-sm text-slate-300">
              <input
                type="checkbox"
                className="h-4 w-4 rounded border-ink-600 bg-ink-900"
                checked={settings.schedule_enabled}
                onChange={(event) => update('schedule_enabled', event.target.checked)}
              />
              Automatische Runs aktiv
            </label>
            <label className="flex items-center gap-2 text-sm text-slate-300">
              <input
                type="checkbox"
                className="h-4 w-4 rounded border-ink-600 bg-ink-900"
                checked={settings.keep_thumbnail}
                onChange={(event) => update('keep_thumbnail', event.target.checked)}
              />
              Vorschaubild behalten
            </label>
          </div>
        </div>
      </section>

      <section className="card p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-slate-200">Durchsuchte Seiten</h2>
            <p className="mt-1 text-xs text-slate-500">
              Selektoren und URL-Vorlagen stehen in <code>backend/app/scrapers/sites.yaml</code>.
            </p>
          </div>
          <button
            className="btn-ghost"
            onClick={() =>
              void api.reloadSites().then(setSites).then(() => setStatus('sites.yaml neu geladen.'))
            }
          >
            sites.yaml neu laden
          </button>
        </div>
        <ul className="mt-4 space-y-2">
          {sites.map((site) => (
            <li
              key={site.key}
              className="flex flex-wrap items-center gap-3 rounded-lg bg-ink-900/60 px-3 py-2 text-sm"
            >
              <span
                className={`chip ${
                  site.enabled ? 'bg-emerald-950 text-emerald-300' : 'bg-ink-700 text-slate-400'
                }`}
              >
                {site.enabled ? 'aktiv' : 'aus'}
              </span>
              <span className="font-medium text-slate-200">{site.name}</span>
              <span className="chip bg-ink-700 text-slate-400">{site.fetcher}</span>
              <code className="truncate text-xs text-slate-500">{site.search_url_template}</code>
            </li>
          ))}
        </ul>
      </section>

      <div className="fixed inset-x-0 bottom-0 border-t border-ink-600/60 bg-ink-900/95 backdrop-blur">
        <div className="mx-auto flex max-w-7xl justify-end px-5 py-3">
          <button className="btn-primary" onClick={save} disabled={saving}>
            {saving ? 'speichert …' : 'Einstellungen speichern'}
          </button>
        </div>
      </div>
    </div>
  )
}
