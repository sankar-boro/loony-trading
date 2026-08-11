import type {
  StatusResponse, PositionsResponse, EquityPoint,
  TradesResponse, DailyResponse, ChartResponse,
  ConfigResponse, BacktestRequest, BacktestJobResponse,
  UniverseResponse, NewsItem, CompositeSignal, WhyResponse, CopilotResponse,
  WatchlistDTO, AlertDTO, AlertTriggerDTO, PortfolioRisk,
} from './types'

const BASE = '/api'

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

async function del<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

async function patch<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { method: 'PATCH' })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

export const api = {
  status:    (): Promise<StatusResponse>   => get('/status'),
  positions: (): Promise<PositionsResponse> => get('/positions'),
  equity:    (): Promise<EquityPoint[]>     => get('/equity'),
  trades:    (source: 'paper' | 'live' = 'paper'): Promise<TradesResponse> =>
    get(`/trades?source=${source}`),
  daily:     (): Promise<DailyResponse>    => get('/daily'),
  config:    (): Promise<ConfigResponse>   => get('/config'),
  chart:     (symbol: string, interval: string, days: number): Promise<ChartResponse> =>
    get(`/chart/${symbol}?interval=${interval}&days=${days}`),
  ltp:       (symbols: string[]): Promise<Record<string, number>> =>
    get(`/ltp?symbols=${symbols.join(',')}`),
  submitBacktest: (req: BacktestRequest): Promise<{ job_id: string }> =>
    post('/backtest', req),
  pollBacktest: (jobId: string): Promise<BacktestJobResponse> =>
    get(`/backtest/${jobId}`),
  universe: (): Promise<UniverseResponse> => get('/universe'),
  news: (params: { eventType?: string; symbol?: string } = {}): Promise<NewsItem[]> => {
    const q = new URLSearchParams()
    if (params.eventType) q.set('event_type', params.eventType)
    if (params.symbol) q.set('symbol', params.symbol)
    const qs = q.toString()
    return get(`/news${qs ? `?${qs}` : ''}`)
  },
  newsEventTypes: (): Promise<string[]> => get('/news/event-types'),
  ingestNews: (): Promise<{ fetched: number; ingested: number; skipped_duplicate: number; events_created: number }> =>
    post('/news/ingest', {}),
  compositeSignals: (direction?: string): Promise<CompositeSignal[]> =>
    get(`/signals/composite${direction ? `?direction=${direction}` : ''}`),
  compositeSignal: (id: number): Promise<CompositeSignal> =>
    get(`/signals/composite/${id}`),
  whyIsItMoving: (symbol: string): Promise<WhyResponse> =>
    get(`/stocks/${symbol}/why`),
  copilotQuery: (question: string): Promise<CopilotResponse> =>
    post('/copilot/query', { question }),
  listWatchlists: (): Promise<WatchlistDTO[]> => get('/watchlists'),
  createWatchlist: (name: string): Promise<WatchlistDTO> => post('/watchlists', { name }),
  deleteWatchlist: (id: number): Promise<{ deleted: number }> => del(`/watchlists/${id}`),
  addWatchlistItem: (id: number, symbol: string): Promise<WatchlistDTO> =>
    post(`/watchlists/${id}/items`, { symbol }),
  removeWatchlistItem: (id: number, symbol: string): Promise<WatchlistDTO> =>
    del(`/watchlists/${id}/items/${symbol}`),
  listAlerts: (): Promise<AlertDTO[]> => get('/alerts'),
  createAlert: (name: string, condition: Record<string, number>, symbol?: string): Promise<AlertDTO> =>
    post('/alerts', { name, condition, symbol: symbol || null }),
  toggleAlert: (id: number, isActive: boolean): Promise<AlertDTO> =>
    patch(`/alerts/${id}?is_active=${isActive}`),
  deleteAlert: (id: number): Promise<{ deleted: number }> => del(`/alerts/${id}`),
  alertTriggers: (id: number): Promise<AlertTriggerDTO[]> => get(`/alerts/${id}/triggers`),
  evaluateAlerts: (): Promise<{ alerts_checked: number; triggers: unknown[] }> =>
    post('/alerts/evaluate', {}),
  portfolioRisk: (): Promise<PortfolioRisk> => get('/portfolio/risk'),
}

// SWR fetcher
export const fetcher = (url: string) =>
  fetch(url).then(r => { if (!r.ok) throw new Error(r.statusText); return r.json() })
