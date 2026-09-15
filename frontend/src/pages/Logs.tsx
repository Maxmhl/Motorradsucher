import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { api, type LogEntry, type Run } from '../lib/api'
import { dateTime, time } from '../lib/format'
import { useLive } from '../lib/liveContext'

const LEVEL_STYLE: Record<string, string> = {
  error: 'text-rose-400',
  warning: 'text-amber-400',
  info: 'text-slate-300',
  debug: 'text-slate-500',
}

export default function Logs() {
  const live = useLive()
  const [runs, setRuns] = useState<Run[]>([])
  const [runId, setRunId] = useState<number | 'alle'>('alle')
  const [stored, setStored] = useState<LogEntry[]>([])
  const [levels, setLevels] = useState<Set<string>>(new Set(['info', 'warning', 'error']))
  const [follow, setFollow] = useState(true)
  const bottomRef = useRef<HTMLDivElement | null>(null)

  const load = useCallback(async () => {
    const [recentRuns, entries] = await Promise.all([
      api.runs(30),
      api.logs(runId === 'alle' ? undefined : runId),
    ])
    setRuns(recentRuns)
    setStored(entries)
  }, [runId])

  useEffect(() => {
    void load()
  }, [load, live.finishedCount])

  // Live-Meldungen anhängen, aber nur solche, die nicht schon geladen wurden.
  const entries = useMemo(() => {
    const relevant = live.logs.filter(
      (entry) => runId === 'alle' || entry.run_id === runId,
    )
    const known = new Set(stored.map((entry) => `${entry.ts}|${entry.message}`))
    const merged = [...stored, ...relevant.filter((e) => !known.has(`${e.ts}|${e.message}`))]
    return merged.filter((entry) => levels.has(entry.level))
  }, [stored, live.logs, runId, levels])

  useEffect(() => {
    if (follow) bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [entries.length, follow])

  const toggleLevel = (level: string) =>
    setLevels((prev) => {
      const next = new Set(prev)
      if (next.has(level)) next.delete(level)
      else next.add(level)
      return next
    })

  return (
    <div className="space-y-4">
      <div className="card flex flex-wrap items-end gap-4 p-4">
        <div className="w-56">
          <label className="label" htmlFor="run">Run</label>
          <select
            id="run"
            className="field"
            value={String(runId)}
            onChange={(event) =>
              setRunId(event.target.value === 'alle' ? 'alle' : Number(event.target.value))
            }
          >
            <option value="alle">Alle Runs</option>
            {runs.map((run) => (
              <option key={run.id} value={run.id}>
                #{run.id} · {run.status} · {dateTime(run.started_at)}
              </option>
            ))}
          </select>
        </div>
        <div>
          <span className="label">Level</span>
          <div className="flex gap-1">
            {['debug', 'info', 'warning', 'error'].map((level) => (
              <button
                key={level}
                onClick={() => toggleLevel(level)}
                className={`chip border ${
                  levels.has(level)
                    ? 'border-sky-700 bg-sky-950 text-sky-300'
                    : 'border-ink-600 text-slate-500'
                }`}
              >
                {level}
              </button>
            ))}
          </div>
        </div>
        <label className="flex items-center gap-2 pb-1 text-sm text-slate-300">
          <input
            type="checkbox"
            className="h-4 w-4 rounded border-ink-600 bg-ink-900"
            checked={follow}
            onChange={(event) => setFollow(event.target.checked)}
          />
          Automatisch mitscrollen
        </label>
        <button className="btn-ghost ml-auto" onClick={() => void load()}>
          Neu laden
        </button>
      </div>

      <div className="card max-h-[65vh] overflow-y-auto p-4 font-mono text-xs leading-relaxed">
        {entries.length === 0 ? (
          <p className="text-slate-500">Keine Logeinträge für diese Auswahl.</p>
        ) : (
          entries.map((entry) => (
            <div key={entry.id} className="flex gap-3 py-0.5">
              <span className="shrink-0 text-slate-600">{time(entry.ts)}</span>
              <span className="w-16 shrink-0 text-slate-600">{entry.stage ?? '–'}</span>
              <span className={`${LEVEL_STYLE[entry.level] ?? 'text-slate-300'} break-all`}>
                {entry.message}
              </span>
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
