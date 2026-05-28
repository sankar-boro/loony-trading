import type {
  StatusResponse, PositionsResponse, EquityPoint,
  TradesResponse, DailyResponse, ChartResponse,
  ConfigResponse, BacktestRequest, BacktestJobResponse,
  UniverseResponse,
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
}

// SWR fetcher
export const fetcher = (url: string) =>
  fetch(url).then(r => { if (!r.ok) throw new Error(r.statusText); return r.json() })
