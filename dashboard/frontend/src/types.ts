export interface StatusResponse {
  bot_running: boolean
  market_open: boolean
  mins_to_close: number
  next_market_open: string
  token_valid: boolean
  token_age_h: number
  demo_mode: boolean
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
  benchmark?: boolean
  walk_forward?: boolean
  walk_forward_splits?: number
  monte_carlo?: boolean
}

export interface BacktestBenchmark {
  bench_return_pct: number
  strat_return_pct: number
  alpha_pct: number
  beta: number
  info_ratio: number
}

export interface BacktestMonteCarlo {
  sharpe_mean: number
  sharpe_p5: number
  sharpe_p95: number
  max_dd_mean: number
  max_dd_p95: number
  return_mean_pct: number
  p_value_sharpe: number
  error?: string
}

export interface BacktestTradeDetail {
  direction: number
  entry_price: number
  exit_price: number
  size: number
  entry_bar: number
  exit_bar: number
  pnl: number
  strategy: string
  reason: string
}

export interface BacktestResult {
  symbol: string
  n_trades: number
  win_rate: number
  total_return_pct: number
  cagr_pct: number
  sharpe: number
  sortino: number
  max_drawdown_pct: number
  profit_factor: number
  avg_win: number
  avg_loss: number
  expectancy: number
  median_trade_return_pct: number
  avg_holding_bars: number
  equity_curve: number[]
  trades_pnl: number[]
  trades?: BacktestTradeDetail[]
  benchmark?: BacktestBenchmark
  monte_carlo?: BacktestMonteCarlo
}

export interface BacktestWalkForwardSplit extends BacktestResult {
  split_index: number
}

export interface BacktestWalkForwardResult {
  symbol: string
  strategy: string | string[]
  walk_forward: true
  splits: BacktestWalkForwardSplit[]
  final_split: BacktestResult
  monte_carlo?: BacktestMonteCarlo
}

export interface BacktestJobResult {
  symbols: string[]
  results: (BacktestResult | BacktestWalkForwardResult)[]
  errors?: { symbol: string; error: string }[]
}

export interface BacktestJobResponse {
  job_id: string
  status: 'pending' | 'running' | 'done' | 'error'
  result?: BacktestJobResult
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

export interface UniverseStock {
  symbol: string
  name: string
  industry: string
  market_cap: string
  fno: boolean
  nifty50: boolean
}

export interface UniverseSector {
  sector: string
  color: string
  stocks: UniverseStock[]
}

export interface UniverseResponse {
  sectors: UniverseSector[]
  total_stocks: number
  watchlist: string[]
}

export interface ScoreComponents {
  catalyst: number
  technical: number
  momentum: number
  volume: number
  historical: number
  regime: number
  risk: number
}

export interface TradeSetup {
  entry_low: number
  entry_high: number
  stop_loss: number
  target_1: number
  target_2: number | null
  risk_reward: number | null
}

export interface CompositeSignal {
  id: number
  symbol: string
  timeframe: string
  timestamp: string
  direction: 'bullish' | 'bearish' | 'watch' | 'no_signal'
  score: number
  confidence: number
  components: ScoreComponents
  explanation: ScoreComponents
  trade_setup: TradeSetup | null
}

export interface IntradayScanRequest {
  symbols?: string[]
  limit?: number | null
  lookback_days?: number
  timeframe?: string
}

export interface IntradayScanResult {
  symbol: string
  direction: 'bullish' | 'bearish' | 'watch' | 'no_signal'
  score: number
  confidence: number
}

export interface IntradayScanResponse {
  universe: number
  scored: number
  skipped: number
  timeframe: string
  directions: Record<string, number>
  results: IntradayScanResult[]
  errors: { symbol: string; error: string }[]
}

export interface AlertEvaluateResponse {
  alerts_checked: number
  timeframe: string
  triggers: { alert_id: number; alert_name: string; symbol: string; matched_values: Record<string, unknown> }[]
}

export interface SchedulerJobRun {
  name: string
  started_at: string
  ok: boolean
  detail: unknown
  duration_ms: number
}

export interface SchedulerStatus {
  running: boolean
  next_runs: Record<string, string | null>
  last_runs: Record<string, SchedulerJobRun>
}

export interface WhyDriver {
  factor: string
  label: string
  score: number
  weight: number
  contribution: number
}

export interface WhyHistoricalAnalogue {
  event_type: string
  direction: string | null
  sample_count: number
  win_rate_pct: number | null
  median_return_pct: number | null
  label: string
}

export interface WhyResponse {
  symbol: string
  signal: { direction: string; score: number; confidence: number; timestamp: string } | null
  drivers: WhyDriver[]
  recent_news: {
    headline: string; source: string; url: string; published_at: string
    event_type: string; sentiment_score: number; impact_score: number; summary: string
  }[]
  historical_analogue: WhyHistoricalAnalogue | null
  conclusion: string
}

export interface CopilotResponse {
  answer: string
  confidence: 'low' | 'medium' | 'high'
  evidence: string[]
  insufficient_evidence: boolean
}

export interface WatchlistDTO {
  id: number
  name: string
  created_at: string
  symbols: string[]
}

export interface AlertDTO {
  id: number
  name: string
  symbol: string | null
  condition: Record<string, number>
  is_active: boolean
  triggered_at: string | null
  created_at: string
}

export interface AlertTriggerDTO {
  id: number
  symbol: string
  signal_id: number | null
  matched_values: Record<string, number>
  created_at: string
}

export interface PortfolioRiskWarning {
  type: 'sector_concentration' | 'high_correlation' | 'total_exposure' | 'daily_loss_limit'
  severity: 'warning' | 'critical'
  message: string
}

export interface PortfolioRisk {
  capital: number
  cash: number
  market_value: number
  open_positions: number
  daily_pnl: number
  unrealized_pnl: number
  exposure_pct: number
  max_loss: number
  sector_exposure_pct: Record<string, number>
  correlation: Record<string, Record<string, number | null>>
  warnings: PortfolioRiskWarning[]
}

export interface NewsItem {
  id: number
  headline: string
  source: string
  url: string
  published_at: string
  event_type: string
  sentiment_score: number
  impact_score: number
  confidence: number
  summary: string
  affected_stocks: string[]
}

export interface DocSection {
  id: string
  title: string
}

export interface DocChapter {
  path: string
  title: string
  number: number
  sections: DocSection[]
}

export interface DocPart {
  title: string
  chapters: DocChapter[]
}

export interface DocBook {
  title: string
  subtitle: string
  parts: DocPart[]
}

export interface DocSearchHit {
  path: string
  chapter: string
  number: number
  section_id: string
  section: string
  snippet: string
}

// ── Intraday Desk (/api/intraday/desk) ───────────────────────────────────────

export type SessionPhase =
  | 'pre_open' | 'opening' | 'entry_window' | 'manage_only'
  | 'squareoff' | 'closed' | 'weekend' | 'holiday'

export interface DeskSession {
  now: string
  phase: SessionPhase
  trading_day: boolean
  market_open: string
  squareoff: string
  market_close: string
  entry_start: string
  entry_end: string
  mins_to_entry_end: number
  mins_to_squareoff: number
  mins_to_close: number
}

export interface DeskGuard {
  session_date: string | null
  entry_start: string
  entry_end: string
  in_entry_window: boolean | null
  max_trades_per_day: number
  max_trades_per_symbol: number
  trades_today: number
  trades_by_symbol: Record<string, number>
  cooldowns: Record<string, string>
  max_daily_loss_pct: number
  profit_lock_pct: number
  halted: boolean
  halt_reason: string
  paused: boolean
}

export interface DeskPosition extends Position {
  product?: string
  stop_order_id?: string
}

export interface DeskEvent {
  ts: string
  kind: 'entry' | 'exit' | 'block' | 'halt' | 'flatten' | 'control' | 'error' | 'heartbeat' | 'squareoff' | string
  message: string
}

export interface DeskTrade extends Trade {
  type: 'close'
}

export interface DeskResponse {
  session: DeskSession
  bot: {
    running: boolean
    mode: 'paper' | 'live' | null
    saved_at: number
    last_tick_at: number
    feed_age_sec: number | null
    feed_stale: boolean
    exchange_stops: boolean
  }
  guard: DeskGuard
  control: { paused?: boolean; flatten_id?: string; resume_id?: string; updated_at?: number }
  pnl: {
    realised: number
    unrealised: number
    day: number
    capital: number
    loss_limit: number
    loss_used_pct: number
    profit_lock: number
  }
  positions: DeskPosition[]
  trades: DeskTrade[]
  by_strategy: { strategy: string; trades: number; wins: number; pnl: number }[]
  curve: { ts: string; realised: number; unrealised: number; total: number; open_positions: number }[]
  events: DeskEvent[]
}

export type DeskAction = 'pause' | 'resume' | 'flatten'
