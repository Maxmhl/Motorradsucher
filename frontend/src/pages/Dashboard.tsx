import { useCallback, useEffect, useState } from 'react'

import { api, type Dashboard as DashboardData, type Run, type StageStat } from '../lib/api'
import { dateTime, duration, num } from '../lib/format'
import { useLive } from '../lib/liveContext'

const STAGES: { key: string; label: string }[] = [
  { key: 'scrape', label: '1 · Scraping' },
  { key: 'text', label: '2 · Text-Analyse' },
  { key: 'vision', label: '3 · Bild-Analyse' },
  { key: 'classify', label: '4 · Klassifizierung' },
  { key: 'cleanup', label: '5 · Bilder löschen' },
  { key: 'rank', label: '6 · Ranking' },
]

function StageBar({ stat, label }: { stat: StageStat | undefined; label: string }) {
  const total = stat?.total ?? 0
  const done = stat?.done ?? 0
  const state = stat?.state ?? 'pending'
  const percent = total > 0 ? Math.min(100, (done / total) * 100) : state === 'done' ? 100 : 0

  const extras = Object.entries(stat ?? {})
    .filter(([key, value]) => !['done', 'total', 'state'].includes(key) && typeof value === 'number')
    .map(([key, value]) => `${key}: ${value}`)

  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between text-sm">
        <span className={state === 'pending' ? 'text-slate-500' : 'text-slate-200'}>{label}</span>
        <span className="tabular-nums text-xs text-slate-400">
          {total > 0 ? `${done} / ${total}` : state === 'done' ? 'fertig' : '–'}
        </span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-ink-700">
        <div
          className={`h-full rounded-full transition-all duration-500 ${
            state === 'done' ? 'bg-emerald-600' : state === 'running' ? 'bg-sky-500' : 'bg-ink-600'
          }`}
          style={{ width: `${percent}%` }}
        />
      </div>
      {extras.length > 0 && (
        <p className="mt-1 text-[11px] text-slate-500">{extras.join(' · ')}</p>
      )}
    </div>
  )
}

function Metric({ label, value, tone }: { label: string; value: number; tone?: string }) {
  return (
    <div className="card px-4 py-3">
      <p className="text-xs uppercase tracking-wide text-slate-500">{label}</p>
      <p className={`mt-1 text-2xl font-semibold tabular-nums ${tone ?? 'text-slate-100'}`}>
        {num(value)}
      </p>
    </div>
  )
}

export default function Dashboard() {
  const live = useLive()
  const [data, setData] = useState<DashboardData | null>(null)
  const [runs, setRuns] = useState<Run[]>([])
  const [error, setError] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)

  const load = useCallback(async () => {
    try {
      const [dashboard, recentRuns] = await Promise.all([api.dashboard(), api.runs(8)])
      setData(dashboard)
      setRuns(recentRuns)
      setError(null)
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc))
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load, live.finishedCount])

  // Waehrend eines Runs regelmaessig nachladen - der WebSocket liefert den
  // Fortschritt, die Kennzahlen kommen aus der DB.
  useEffect(() => {
    if (!live.busy) return
    const timer = window.setInterval(() => void load(), 5000)
    return () => window.clearInterval(timer)
  }, [live.busy, load])

  const stats = live.busy ? live.stats : (data?.latest_run?.stage_stats ?? {})
  const counts = data?.counts ?? {}

  const startRun = async () => {
    setStarting(true)
    try {
      await api.startRun()
      setError(null)
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc))
    } finally {
      setStarting(false)
      void load()
    }
  }

  return (
    <div className="space-y-6">
      {error && (
        <div className="card border-rose-900/70 bg-rose-950/40 px-4 py-3 text-sm text-rose-200">
          {error}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <button className="btn-primary" onClick={startRun} disabled={live.busy || starting}>
          {live.busy ? 'Run läuft …' : 'Suche jetzt starten'}
        </button>
        {live.busy && (
          <button className="btn-danger" onClick={() => void api.cancelRun()}>
            Abbrechen
          </button>
        )}
        {data?.scheduler.scheduled && (
          <span className="text-sm text-slate-400">
            Nächster automatischer Run: {dateTime(data.scheduler.next_run)}
          </span>
        )}
      </div>

      {data?.ollama.some((endpoint) => !endpoint.reachable) && (
        <div className="card border-amber-900/70 bg-amber-950/30 px-4 py-3 text-sm text-amber-200">
          <p className="font-medium">Ollama nicht erreichbar</p>
          <ul className="mt-1 space-y-0.5 text-amber-200/80">
            {data.ollama
              .filter((endpoint) => !endpoint.reachable)
              .map((endpoint) => (
                <li key={endpoint.url}>
                  {endpoint.url} ({endpoint.stages.join(', ')}) — {endpoint.error}
                </li>
              ))}
          </ul>
          <p className="mt-2 text-xs text-amber-200/70">
            Ohne Modell übersprungene Stufen lassen Inserate unbewertet durch.
          </p>
        </div>
      )}

      <section className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <Metric label="Inserate gesamt" value={counts.gesamt ?? 0} />
        <Metric label="Neu" value={counts.new ?? 0} />
        <Metric label="Text abgelehnt" value={counts.text_rejected ?? 0} tone="text-amber-400" />
        <Metric label="Optik abgelehnt" value={counts.optical_rejected ?? 0} tone="text-amber-400" />
        <Metric label="Passend" value={counts.passend ?? 0} tone="text-emerald-400" />
        <Metric label="Fehler" value={counts.error ?? 0} tone="text-rose-400" />
      </section>

      <section className="card p-5">
        <h2 className="mb-4 text-sm font-semibold text-slate-200">
          Pipeline {live.busy ? `— Run ${live.runId}` : data?.latest_run ? `— letzter Run ${data.latest_run.id}` : ''}
        </h2>
        <div className="space-y-4">
          {STAGES.map((stage) => (
            <StageBar key={stage.key} label={stage.label} stat={stats[stage.key]} />
          ))}
        </div>
      </section>

      <section className="card overflow-hidden">
        <h2 className="border-b border-ink-600/60 px-5 py-3 text-sm font-semibold text-slate-200">
          Letzte Runs
        </h2>
        {runs.length === 0 ? (
          <p className="px-5 py-6 text-sm text-slate-500">Noch kein Run gelaufen.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs uppercase tracking-wide text-slate-500">
                <tr className="border-b border-ink-600/60">
                  <th className="px-5 py-2 font-medium">#</th>
                  <th className="px-5 py-2 font-medium">Status</th>
                  <th className="px-5 py-2 font-medium">Auslöser</th>
                  <th className="px-5 py-2 font-medium">Start</th>
                  <th className="px-5 py-2 font-medium">Dauer</th>
                  <th className="px-5 py-2 font-medium">Neu</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr key={run.id} className="border-b border-ink-700/40 last:border-0">
                    <td className="px-5 py-2 tabular-nums text-slate-400">{run.id}</td>
                    <td className="px-5 py-2">
                      <span
                        className={`chip ${
                          run.status === 'finished'
                            ? 'bg-emerald-950 text-emerald-300'
                            : run.status === 'running'
                              ? 'bg-sky-950 text-sky-300'
                              : run.status === 'cancelled'
                                ? 'bg-ink-700 text-slate-300'
                                : 'bg-rose-950 text-rose-300'
                        }`}
                      >
                        {run.status}
                      </span>
                    </td>
                    <td className="px-5 py-2 text-slate-400">{run.trigger}</td>
                    <td className="px-5 py-2 text-slate-400">{dateTime(run.started_at)}</td>
                    <td className="px-5 py-2 tabular-nums text-slate-400">
                      {duration(run.started_at, run.finished_at)}
                    </td>
                    <td className="px-5 py-2 tabular-nums text-slate-400">
                      {num((run.stage_stats?.scrape?.new as number) ?? null)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}
