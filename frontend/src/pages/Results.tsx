import { useCallback, useEffect, useState } from 'react'

import ListingCard from '../components/ListingCard'
import { api, type FinalClass, type Listing } from '../lib/api'
import { useLive } from '../lib/liveContext'

const TABS: { key: FinalClass; label: string; limited: boolean }[] = [
  { key: 'passend', label: 'Passend', limited: false },
  { key: 'unpassende_optik', label: 'Unpassende Optik', limited: true },
  { key: 'unpassender_zustand', label: 'Unpassender Zustand', limited: true },
]

const SORTS = [
  { value: 'score', label: 'Ranking-Score' },
  { value: 'price', label: 'Preis' },
  { value: 'km', label: 'Laufleistung' },
  { value: 'year', label: 'Baujahr' },
  { value: 'first_seen', label: 'Zuerst gesehen' },
]

export default function Results() {
  const live = useLive()
  const [tab, setTab] = useState<FinalClass>('passend')
  const [items, setItems] = useState<Listing[]>([])
  const [total, setTotal] = useState(0)
  const [hidden, setHidden] = useState(0)
  const [showAll, setShowAll] = useState(false)
  const [sort, setSort] = useState('score')
  const [direction, setDirection] = useState('desc')
  const [search, setSearch] = useState('')
  const [priceMax, setPriceMax] = useState('')
  const [kmMax, setKmMax] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const page = await api.listings({
        final_class: tab,
        sort,
        direction,
        search,
        price_max: priceMax,
        km_max: kmMax,
        show_all: showAll,
        limit: 200,
      })
      setItems(page.items)
      setTotal(page.total)
      setHidden(page.hidden)
      setError(null)
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc))
    } finally {
      setLoading(false)
    }
  }, [tab, sort, direction, search, priceMax, kmMax, showAll])

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 250)
    return () => window.clearTimeout(timer)
  }, [load, live.finishedCount])

  // Beim Tab-Wechsel wieder auf die Top-N-Ansicht zurück.
  useEffect(() => setShowAll(false), [tab])

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap gap-1 border-b border-ink-600/60">
        {TABS.map((item) => (
          <button
            key={item.key}
            onClick={() => setTab(item.key)}
            className={`-mb-px rounded-t-lg border-b-2 px-4 py-2 text-sm transition ${
              tab === item.key
                ? 'border-sky-500 text-white'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            {item.label}
          </button>
        ))}
      </div>

      <div className="card flex flex-wrap items-end gap-3 p-4">
        <div className="min-w-[180px] flex-1">
          <label className="label" htmlFor="search">Suche in Titel & Beschreibung</label>
          <input
            id="search"
            className="field"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="z. B. Scheckheft"
          />
        </div>
        <div className="w-32">
          <label className="label" htmlFor="price-max">Preis bis</label>
          <input
            id="price-max"
            className="field"
            type="number"
            value={priceMax}
            onChange={(event) => setPriceMax(event.target.value)}
            placeholder="€"
          />
        </div>
        <div className="w-32">
          <label className="label" htmlFor="km-max">km bis</label>
          <input
            id="km-max"
            className="field"
            type="number"
            value={kmMax}
            onChange={(event) => setKmMax(event.target.value)}
          />
        </div>
        <div className="w-44">
          <label className="label" htmlFor="sort">Sortierung</label>
          <select
            id="sort"
            className="field"
            value={sort}
            onChange={(event) => setSort(event.target.value)}
          >
            {SORTS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
        <button
          className="btn-ghost"
          onClick={() => setDirection((value) => (value === 'desc' ? 'asc' : 'desc'))}
          title="Sortierrichtung umkehren"
        >
          {direction === 'desc' ? 'absteigend ↓' : 'aufsteigend ↑'}
        </button>
      </div>

      {error && (
        <div className="card border-rose-900/70 bg-rose-950/40 px-4 py-3 text-sm text-rose-200">
          {error}
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3 text-sm text-slate-400">
        <span>
          {loading ? 'lädt …' : `${items.length} von ${total} Inserat(en)`}
        </span>
        {hidden > 0 && !showAll && (
          <button className="btn-ghost" onClick={() => setShowAll(true)}>
            {hidden} weitere ausgeblendet — alle anzeigen
          </button>
        )}
        {showAll && (
          <button className="btn-ghost" onClick={() => setShowAll(false)}>
            Nur Top-Treffer zeigen
          </button>
        )}
      </div>

      {!loading && items.length === 0 ? (
        <div className="card px-5 py-10 text-center text-sm text-slate-500">
          Keine Inserate in dieser Klasse. Starte einen Run im Dashboard.
        </div>
      ) : (
        <div className="space-y-3">
          {items.map((listing) => (
            <ListingCard key={listing.id} listing={listing} />
          ))}
        </div>
      )}
    </div>
  )
}
