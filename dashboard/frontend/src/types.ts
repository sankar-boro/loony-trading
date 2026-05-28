export interface StatusResponse {
  bot_running: boolean
  market_open: boolean
  mins_to_close: number
  next_market_open: string
  token_valid: boolean
  token_age_h: number
}

export interface Position {
  symbol: string
  direction: 1 | -1
  size: number
  entry_price: number
  current_price: number
  unrealised_pnl: number
  stop_loss: number
  take_profit: number
  strategy: string
  entry_time: string
  peak_price: number
}

export interface SignalEvent {
  time: string
  type: string
  symbol: string
  price?: number
  size?: number
  pnl?: number
  strategy?: string
  confidence?: number
  reason?: string
}

export interface PositionsResponse {
  positions: Position[]
  signal_log: SignalEvent[]
  cash: number
  initial_capital: number
  saved_at: number
}

export interface EquityPoint {
  ts: string
  equity: number
  cash: number
  realised: number
  unrealised: number
  open_pos: number
}

export interface Trade {
  ts: string
  symbol: string
  direction: number
  strategy: string
  entry_price: number
  exit_price: number
  size: number
  pnl: number
  reason: string
}

export interface TradeStats {
  total: number
  wins: number
  losses: number
  win_rate: number
  total_pnl: number
  avg_win: number
  avg_loss: number
  expectancy: number
  profit_factor: number
}

export interface TradesResponse {
  trades: Trade[]
  stats: TradeStats
}

export interface DailyRecord {
  date: string
  realised: number
  unrealised: number
  trades: number
  wins: number
  losses: number
  win_rate: number
  max_drawdown_pct: number
  top_symbol: string
}

export interface DailyResponse {
  days: DailyRecord[]
  summary: {
    total_realised: number
    avg_daily: number
    best_day: DailyRecord | null
    worst_day: DailyRecord | null
    sharpe_ann: number
    total_trades: number
    overall_win_rate: number
  }
}

export interface Candle {
  time: number
  open: number
  high: number
  low: number
  close: number
  volume: number
}

export interface ChartResponse {
  symbol: string
  interval: string
  candles: Candle[]
}

export interface ConfigResponse {
  weights: Record<string, number>
  enabled: string[]
  capital: number
  all_strategies: string[]
}

export interface StrategyStats {
  strategy: string
  trades: number
  wins: number
  win_rate: number
  total_pnl: number
  avg_pnl: number
}

export interface BacktestRequest {
  symbol: string
  strategy: string
  days: number
  capital: number
}

export interface BacktestResult {
  symbol: string
  strategy: string
  n_trades: number
  win_rate: number
  total_return_pct: number
  sharpe: number
  max_drawdown_pct: number
  profit_factor: number
  equity_curve: number[]
  trades_pnl: number[]
}

export interface BacktestJobResponse {
  job_id: string
  status: 'pending' | 'running' | 'done' | 'error'
  result?: BacktestResult
  error?: string
}

export interface WatchlistItem {
  ltp: number
  change: number
  change_pct: number
  volume: number
}
export type WatchlistResponse = Record<string, WatchlistItem>

export interface MarketIndex {
  ltp: number
  change_pct: number
}
export type MarketResponse = Record<string, MarketIndex>

export interface SignalItem {
  symbol: string
  signal: string
  strategy: string
  confidence: number
  price: number
  stop_loss: number
  take_profit: number
  ts: string
}
