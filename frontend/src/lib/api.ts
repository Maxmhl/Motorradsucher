// Typen und Zugriff auf die FastAPI-Endpunkte.

export type FinalClass = 'passend' | 'unpassende_optik' | 'unpassender_zustand'

export interface Verdict {
  verdict?: string
  confidence?: number
  findings?: string[]
  matched?: string[]
  violated?: string[]
  reasoning?: string
}

export interface ListingImage {
  id: number
  source_url: string
  vision_description: string | null
  deleted_at: string | null
}

export interface Listing {
  id: number
  url: string
  site: string | null
  title: string | null
  model: string | null
  price: number | null
  year: number | null
  km: number | null
  location: string | null
  description: string | null
  status: string
  final_class: FinalClass | null
  text_verdict: Verdict | null
  text_reasoning: string | null
  optical_verdict: Verdict | null
  optical_reasoning: string | null
  rank_score: number | null
  rank_reasoning: string | null
  rank_position: number | null
  thumbnail_url: string | null
  first_seen: string
  last_updated: string
  images: ListingImage[]
}

export interface ListingPage {
  items: Listing[]
  total: number
  hidden: number
}

export interface StageStat {
  done: number
  total: number
  state: 'pending' | 'running' | 'done'
  [key: string]: unknown
}

export interface Run {
  id: number
  status: string
  trigger: string
  started_at: string
  finished_at: string | null
  stage_stats: Record<string, StageStat>
  error_message: string | null
}

export interface LogEntry {
  id: number
  run_id: number | null
  ts: string
  level: string
  stage: string | null
  message: string
}

export interface OllamaModel {
  name: string
  size_gb: number | null
  parameter_size: string | null
  quantization: string | null
  family: string | null
  fit: 'single_gpu' | 'tensor_split' | 'too_large' | 'unknown'
  vision_capable: boolean
}

export interface ModelsResponse {
  endpoints: { url: string; stages: string; reachable: boolean; count: number }[]
  models: OllamaModel[]
  error: string | null
}

export interface Criteria {
  budget_max: number
  year_min: number
  km_max: number
  models: string[]
  zip_code: string
  radius_km: number
}

export interface AppSettings {
  text_model: string
  vision_model: string
  interpretation_model: string
  ranking_model: string
  criteria: Criteria
  text_exclusions: string
  optical_criteria: string
  top_n_rejected: number
  keep_thumbnail: boolean
  max_listings_per_run: number
  schedule_enabled: boolean
  schedule_cron: string
}

export interface Dashboard {
  runner: { busy: boolean; run_id: number | null; stage: string | null; stats: Record<string, StageStat> }
  scheduler: { running: boolean; scheduled: boolean; next_run: string | null; timezone: string }
  latest_run: Run | null
  counts: Record<string, number>
  ollama: { url: string; reachable: boolean; error: string | null; stages: string[]; models: number }[]
}

export interface Site {
  key: string
  name: string
  enabled: boolean
  fetcher: string
  search_url_template: string
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  if (!response.ok) {
    let detail = `HTTP ${response.status}`
    try {
      const body = await response.json()
      if (body?.detail) detail = String(body.detail)
    } catch {
      /* Antwort war kein JSON - Statuscode reicht */
    }
    throw new Error(detail)
  }
  return response.json() as Promise<T>
}

export const api = {
  dashboard: () => request<Dashboard>('/api/dashboard'),
  runs: (limit = 20) => request<Run[]>(`/api/runs?limit=${limit}`),
  startRun: () => request<Run>('/api/runs', { method: 'POST' }),
  cancelRun: () => request<{ cancelled: boolean }>('/api/runs/cancel', { method: 'POST' }),
  logs: (runId?: number, limit = 300) =>
    request<LogEntry[]>(`/api/logs?limit=${limit}${runId ? `&run_id=${runId}` : ''}`),
  listings: (params: Record<string, string | number | boolean | undefined>) => {
    const query = new URLSearchParams()
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== '') query.set(key, String(value))
    }
    return request<ListingPage>(`/api/listings?${query.toString()}`)
  },
  settings: () => request<AppSettings>('/api/settings'),
  saveSettings: (values: Partial<AppSettings>) =>
    request<{ settings: AppSettings; schedule: { next_run: string | null; error: string | null } | null }>(
      '/api/settings',
      { method: 'PUT', body: JSON.stringify(values) },
    ),
  models: () => request<ModelsResponse>('/api/models'),
  testModel: (model: string, stage: string) =>
    request<{ ok: boolean; response?: string; error?: string }>('/api/models/test', {
      method: 'POST',
      body: JSON.stringify({ model, stage }),
    }),
  sites: () => request<Site[]>('/api/settings/sites'),
  reloadSites: () => request<Site[]>('/api/settings/sites/reload', { method: 'POST' }),
}
