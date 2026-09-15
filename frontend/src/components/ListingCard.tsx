import { useState } from 'react'

import type { Listing } from '../lib/api'
import { dateTime, euro, km } from '../lib/format'

function Confidence({ value }: { value: number | undefined }) {
  if (value == null) return null
  return (
    <span className="text-[11px] text-slate-500">Konfidenz {Math.round(value * 100)} %</span>
  )
}

export default function ListingCard({ listing }: { listing: Listing }) {
  const [open, setOpen] = useState(false)

  const textRejected = listing.text_verdict?.verdict?.startsWith('reject')
  const opticalRejected = listing.optical_verdict?.verdict?.startsWith('reject')
  const descriptions = listing.images.filter((image) => image.vision_description)

  return (
    <article className="card overflow-hidden">
      <div className="flex flex-col gap-4 p-4 sm:flex-row">
        <div className="sm:w-48 sm:shrink-0">
          {listing.thumbnail_url ? (
            <img
              src={listing.thumbnail_url}
              alt={listing.title ?? 'Inserat'}
              loading="lazy"
              className="aspect-[4/3] w-full rounded-lg object-cover"
            />
          ) : (
            <div className="flex aspect-[4/3] w-full items-center justify-center rounded-lg border border-dashed border-ink-600 text-xs text-slate-600">
              kein Bild
            </div>
          )}
          {listing.rank_score != null && (
            <div className="mt-2 flex items-center justify-between text-xs">
              <span className="text-slate-500">
                {listing.rank_position ? `Platz ${listing.rank_position}` : 'Score'}
              </span>
              <span className="font-semibold tabular-nums text-sky-400">
                {Math.round(listing.rank_score)}
              </span>
            </div>
          )}
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <h3 className="text-base font-medium leading-snug text-slate-100">
              <a href={listing.url} target="_blank" rel="noreferrer" className="hover:text-sky-400">
                {listing.title ?? listing.url}
              </a>
            </h3>
            <span className="chip bg-ink-700 text-slate-400">{listing.site ?? '–'}</span>
          </div>

          <dl className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-sm">
            <div className="flex gap-1.5">
              <dt className="text-slate-500">Preis</dt>
              <dd className="font-medium text-slate-100">{euro(listing.price)}</dd>
            </div>
            <div className="flex gap-1.5">
              <dt className="text-slate-500">Baujahr</dt>
              <dd className="text-slate-200">{listing.year ?? '–'}</dd>
            </div>
            <div className="flex gap-1.5">
              <dt className="text-slate-500">Laufleistung</dt>
              <dd className="text-slate-200">{km(listing.km)}</dd>
            </div>
            {listing.location && (
              <div className="flex gap-1.5">
                <dt className="text-slate-500">Ort</dt>
                <dd className="truncate text-slate-200">{listing.location}</dd>
              </div>
            )}
          </dl>

          {listing.rank_reasoning && (
            <p className="mt-3 border-l-2 border-sky-800 pl-3 text-sm leading-relaxed text-slate-300">
              {listing.rank_reasoning}
            </p>
          )}

          <div className="mt-3 flex flex-wrap gap-2">
            <span
              className={`chip ${
                textRejected ? 'bg-rose-950 text-rose-300' : 'bg-emerald-950 text-emerald-300'
              }`}
            >
              Zustand: {textRejected ? 'abgelehnt' : 'ok'}
            </span>
            <span
              className={`chip ${
                opticalRejected
                  ? 'bg-amber-950 text-amber-300'
                  : listing.optical_verdict
                    ? 'bg-emerald-950 text-emerald-300'
                    : 'bg-ink-700 text-slate-400'
              }`}
            >
              Optik: {opticalRejected ? 'abgelehnt' : listing.optical_verdict ? 'ok' : 'nicht geprüft'}
            </span>
            <button
              className="chip border border-ink-600 text-slate-400 hover:bg-ink-700"
              onClick={() => setOpen((value) => !value)}
            >
              {open ? 'Details ausblenden' : 'Details'}
            </button>
            <a
              href={listing.url}
              target="_blank"
              rel="noreferrer"
              className="chip border border-ink-600 text-sky-400 hover:bg-ink-700"
            >
              Original öffnen ↗
            </a>
          </div>
        </div>
      </div>

      {open && (
        <div className="space-y-4 border-t border-ink-600/60 bg-ink-900/40 px-4 py-4 text-sm">
          <section>
            <h4 className="mb-1 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
              Text-Analyse <Confidence value={listing.text_verdict?.confidence} />
            </h4>
            <p className="text-slate-300">{listing.text_reasoning || 'Keine Bewertung vorhanden.'}</p>
            {listing.text_verdict?.findings && listing.text_verdict.findings.length > 0 && (
              <ul className="mt-1 list-inside list-disc text-slate-400">
                {listing.text_verdict.findings.map((finding, index) => (
                  <li key={index}>{finding}</li>
                ))}
              </ul>
            )}
          </section>

          <section>
            <h4 className="mb-1 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
              Optik-Bewertung <Confidence value={listing.optical_verdict?.confidence} />
            </h4>
            <p className="text-slate-300">
              {listing.optical_reasoning || 'Keine Bewertung vorhanden.'}
            </p>
            {listing.optical_verdict?.violated && listing.optical_verdict.violated.length > 0 && (
              <ul className="mt-1 list-inside list-disc text-amber-300/80">
                {listing.optical_verdict.violated.map((item, index) => (
                  <li key={index}>{item}</li>
                ))}
              </ul>
            )}
          </section>

          {descriptions.length > 0 && (
            <section>
              <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
                Bildbeschreibungen ({descriptions.length})
                <span className="ml-2 font-normal normal-case tracking-normal text-slate-500">
                  Die Bilddateien wurden nach der Analyse gelöscht.
                </span>
              </h4>
              <ol className="space-y-2">
                {descriptions.map((image, index) => (
                  <li key={image.id} className="text-slate-300">
                    <span className="mr-2 text-slate-500">Bild {index + 1}:</span>
                    {image.vision_description}
                  </li>
                ))}
              </ol>
            </section>
          )}

          {listing.description && (
            <section>
              <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
                Original-Beschreibung
              </h4>
              <p className="whitespace-pre-line text-slate-400">{listing.description}</p>
            </section>
          )}

          <p className="text-xs text-slate-600">
            Zuerst gesehen: {dateTime(listing.first_seen)} · Zuletzt aktualisiert:{' '}
            {dateTime(listing.last_updated)}
          </p>
        </div>
      )}
    </article>
  )
}
