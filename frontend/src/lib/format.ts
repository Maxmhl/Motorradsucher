export const euro = (value: number | null | undefined) =>
  value == null ? '–' : `${value.toLocaleString('de-DE')} €`

export const km = (value: number | null | undefined) =>
  value == null ? '–' : `${value.toLocaleString('de-DE')} km`

export const num = (value: number | null | undefined) =>
  value == null ? '–' : value.toLocaleString('de-DE')

export const dateTime = (value: string | null | undefined) =>
  value ? new Date(value).toLocaleString('de-DE', { dateStyle: 'short', timeStyle: 'short' }) : '–'

export const time = (value: string | null | undefined) =>
  value ? new Date(value).toLocaleTimeString('de-DE', { hour12: false }) : '–'

export function duration(from: string, to: string | null): string {
  const seconds = Math.max(0, ((to ? +new Date(to) : Date.now()) - +new Date(from)) / 1000)
  if (seconds < 60) return `${Math.round(seconds)} s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ${Math.round(seconds % 60)} s`
  return `${Math.floor(seconds / 3600)} h ${Math.floor((seconds % 3600) / 60)} min`
}
