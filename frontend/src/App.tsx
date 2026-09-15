import { NavLink, Outlet } from 'react-router-dom'

import { useLiveRun } from './lib/useWebSocket'
import { LiveContext } from './lib/liveContext'

const NAV = [
  { to: '/', label: 'Dashboard', end: true },
  { to: '/ergebnisse', label: 'Ergebnisse', end: false },
  { to: '/einstellungen', label: 'Einstellungen', end: false },
  { to: '/logs', label: 'Logs', end: false },
]

export default function App() {
  const live = useLiveRun()

  return (
    <LiveContext.Provider value={live}>
      <div className="min-h-screen">
        <header className="sticky top-0 z-10 border-b border-ink-600/60 bg-ink-900/90 backdrop-blur">
          <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-6 gap-y-3 px-5 py-3">
            <span className="text-base font-semibold tracking-tight text-white">
              Motorrad-Sucher
            </span>
            <nav className="flex gap-1">
              {NAV.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) =>
                    `rounded-lg px-3 py-1.5 text-sm transition ${
                      isActive
                        ? 'bg-ink-700 text-white'
                        : 'text-slate-400 hover:bg-ink-800 hover:text-slate-200'
                    }`
                  }
                >
                  {item.label}
                </NavLink>
              ))}
            </nav>
            <div className="ml-auto flex items-center gap-2 text-xs text-slate-400">
              <span
                className={`h-2 w-2 rounded-full ${
                  live.connected ? 'bg-emerald-500' : 'bg-slate-600'
                }`}
              />
              {live.connected ? (live.busy ? `Run ${live.runId} läuft` : 'verbunden') : 'getrennt'}
            </div>
          </div>
        </header>
        <main className="mx-auto max-w-7xl px-5 py-6">
          <Outlet />
        </main>
      </div>
    </LiveContext.Provider>
  )
}
