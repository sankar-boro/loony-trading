import { useState, useEffect } from 'react'
import { api } from '../api'
import type {
  BacktestResult, BacktestWalkForwardResult, ConfigResponse, UniverseResponse,
} from '../types'
import useSWR from 'swr'
import { fetcher } from '../api'
import {
  AreaChart, Area, BarChart, Bar, XAxis, YAxis, Tooltip,
  ResponsiveContainer, ReferenceLine, CartesianGrid, Cell,
} from 'recharts'
import clsx from 'clsx'

const PERIODS = [
  { label: '3M', days: 90  },
  { label: '6M', days: 180 },
  { label: '1Y', days: 365 },
  { label: '2Y', days: 730 },
]

const inr    = (n: number) => `₹${Math.abs(n).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
const pnlFmt = (n: number) => `${n >= 0 ? '+' : '-'}${inr(n)}`
const ttStyle = { background: '#161b27', border: '1px solid #252d3d', borderRadius: 8, fontSize: 13 }

// mis_squareoff is the intraday-gap Phase 3 fix (docs/appendix/intraday-audit.md
// §3) — an MIS-product backtest force-closing a position at 3:14 PM IST
// instead of letting it ride across a session boundary. Called out with
// its own color so it reads as a deliberate exit, not a stop/target hit.
const REASON_CLASS: Record<string, string> = {
  stop_loss: 'bg-red/15 text-red', take_profit: 'bg-green/15 text-green',
  mis_squareoff: 'bg-amber-500/15 text-amber-400', end_of_data: 'bg-white/5 text-dim',
}

function Metric({ label, value, up }: { label: string; value: string; up?: boolean }) {
  return (
    <div className="bg-surface border border-border rounded-xl px-4 py-3">
      <div className="text-[11px] text-dim uppercase tracking-wide mb-1">{label}</div>
      <div className={clsx('text-xl font-mono font-semibold',
        up === true ? 'text-green' : up === false ? 'text-red' : 'text-primary')}>
        {value}
      </div>
    </div>
  )
}

export default function Backtest() {
  const { data: cfg }      = useSWR<ConfigResponse>('/api/config', fetcher)
  const { data: universe } = useSWR<UniverseResponse>('/api/universe', fetcher, {
    revalidateOnFocus: false,
  })

  const strategies = cfg?.enabled ?? []
  const allSymbols = universe
    ? universe.sectors.flatMap(s => s.stocks.map(st => st.symbol)).sort()
    : ['RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'ICICIBANK', 'SBIN', 'NIFTY50', 'BANKNIFTY']

  const [symbol,   setSymbol]   = useState('NIFTY50')
  const [strategy, setStrategy] = useState('')
  const [period,   setPeriod]   = useState(PERIODS[1])
  const [capital,  setCapital]  = useState(500_000)
  const [benchmark, setBenchmark]       = useState(false)
  const [walkForward, setWalkForward]   = useState(false)
  const [monteCarlo, setMonteCarlo]     = useState(false)
  const [jobId,    setJobId]    = useState<string | null>(null)
  const [status,   setStatus]   = useState<'idle' | 'running' | 'done' | 'error'>('idle')
  const [result,   setResult]   = useState<BacktestResult | null>(null)
  const [wfSplits, setWfSplits] = useState<BacktestWalkForwardResult['splits'] | null>(null)
  const [errMsg,   setErrMsg]   = useState('')

  const effectiveStrategy = strategy || strategies[0] || 'vwap_reversion'

  // Poll job
  useEffect(() => {
    if (!jobId || status !== 'running') return
    const id = setInterval(async () => {
      try {
        const r = await api.pollBacktest(jobId)
        if (r.status === 'done') {
          setStatus('done')
          const entry = r.result?.results?.[0]
          if (!entry) {
            setStatus('error')
            setErrMsg(r.result?.errors?.[0]?.error ?? 'Backtest produced no result')
          } else if ('walk_forward' in entry && entry.walk_forward) {
            setResult(entry.final_split)
            setWfSplits(entry.splits)
          } else {
            setResult(entry as BacktestResult)
            setWfSplits(null)
          }
          clearInterval(id)
        }
        if (r.status === 'error') { setStatus('error'); setErrMsg(r.error ?? 'Unknown error'); clearInterval(id) }
      } catch {}
    }, 1_500)
    return () => clearInterval(id)
  }, [jobId, status])

  const run = async () => {
    setStatus('running'); setResult(null); setWfSplits(null); setErrMsg('')
    try {
      const { job_id } = await api.submitBacktest({
        symbol, strategy: effectiveStrategy, days: period.days, capital,
        benchmark, walk_forward: walkForward, monte_carlo: monteCarlo,
      })
      setJobId(job_id)
    } catch (e: any) { setStatus('error'); setErrMsg(e.message) }
  }

  // Equity curve
  const eqData = result?.equity_curve.map((v, i) => ({ i, v })) ?? []
  const eqColor = (result?.total_return_pct ?? 0) >= 0 ? '#10b981' : '#f43f5e'

  // P&L histogram
  const histData = (() => {
    if (!result?.trades_pnl.length) return []
    const pnls = result.trades_pnl
    const lo = Math.min(...pnls), hi = Math.max(...pnls)
    const step = (hi - lo) / 16 || 1
    const bins: Record<string, number> = {}
    for (const v of pnls) {
      const k = (Math.floor((v - lo) / step) * step + lo).toFixed(0)
      bins[k] = (bins[k] ?? 0) + 1
    }
    return Object.entries(bins).map(([k, c]) => ({ bin: Number(k), count: c })).sort((a, b) => a.bin - b.bin)
  })()

  return (
    <div className="flex flex-col h-full p-4 gap-3 overflow-hidden">

      <h1 className="text-lg font-semibold tracking-wide shrink-0">Backtest</h1>

      {/* Controls */}
      <div className="bg-surface border border-border rounded-xl p-4 flex flex-wrap gap-4 items-end shrink-0">

        <div className="flex flex-col gap-1.5">
          <label className="text-[11px] text-dim uppercase tracking-wide">Symbol</label>
          <select value={symbol} onChange={e => setSymbol(e.target.value)}
            className="bg-bg border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue min-w-[140px]">
            <optgroup label="Indices">
              {['NIFTY50', 'BANKNIFTY', 'NIFTYIT'].map(s => <option key={s}>{s}</option>)}
            </optgroup>
            {universe?.sectors.map(sec => (
              <optgroup key={sec.sector} label={sec.sector}>
                {sec.stocks.map(st => (
                  <option key={st.symbol}>{st.symbol}</option>
                ))}
              </optgroup>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="text-[11px] text-dim uppercase tracking-wide">Strategy</label>
          <select value={effectiveStrategy} onChange={e => setStrategy(e.target.value)}
            className="bg-bg border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue min-w-[180px]">
            {(strategies.length ? strategies : ['vwap_reversion']).map(s => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="text-[11px] text-dim uppercase tracking-wide">Period</label>
          <div className="flex rounded-lg border border-border overflow-hidden">
            {PERIODS.map(p => (
              <button key={p.days} onClick={() => setPeriod(p)}
                className={clsx('px-4 py-2 text-sm transition-colors',
                  period.days === p.days ? 'bg-blue text-white' : 'text-dim hover:text-primary')}>
                {p.label}
              </button>
            ))}
          </div>
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="text-[11px] text-dim uppercase tracking-wide">Capital ₹</label>
          <input
            type="number" value={capital} onChange={e => setCapital(Number(e.target.value))}
            step={50000} min={10000}
            className="bg-bg border border-border rounded-lg px-3 py-2 text-sm w-36 focus:outline-none focus:border-blue"
          />
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="text-[11px] text-dim uppercase tracking-wide">Options</label>
          <div className="flex gap-3 items-center h-[34px]">
            <label className="flex items-center gap-1.5 text-sm text-dim cursor-pointer">
              <input type="checkbox" checked={benchmark} onChange={e => setBenchmark(e.target.checked)} />
              vs Nifty
            </label>
            <label className="flex items-center gap-1.5 text-sm text-dim cursor-pointer">
              <input type="checkbox" checked={walkForward} onChange={e => setWalkForward(e.target.checked)} />
              Walk-forward
            </label>
            <label className="flex items-center gap-1.5 text-sm text-dim cursor-pointer">
              <input type="checkbox" checked={monteCarlo} onChange={e => setMonteCarlo(e.target.checked)} />
              Monte Carlo
            </label>
          </div>
        </div>

        <button
          onClick={run}
          disabled={status === 'running'}
          className="px-6 py-2 rounded-lg bg-blue text-white text-sm font-medium
                     hover:bg-blue/80 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
        >
          {status === 'running' ? (
            <>
              <span className="w-3 h-3 rounded-full border-2 border-white/30 border-t-white animate-spin" />
              Running…
            </>
          ) : '▷ Run'}
        </button>
      </div>

      {/* Error */}
      {status === 'error' && (
        <div className="bg-red/10 border border-red/30 rounded-xl px-4 py-3 text-sm text-red shrink-0">
          {errMsg}
        </div>
      )}

      {/* Idle placeholder */}
      {status === 'idle' && !result && (
        <div className="flex-1 bg-surface border border-border rounded-xl flex flex-col items-center justify-center gap-2 text-dim">
          <span className="text-4xl opacity-20">▷</span>
          <span className="text-base">Configure and run a backtest above</span>
          <span className="text-sm">Results will appear here</span>
        </div>
      )}

      {/* Results */}
      {result && (
        <div className="flex-1 flex flex-col gap-3 min-h-0 overflow-hidden">
          {/* Metrics */}
          <div className="grid grid-cols-3 md:grid-cols-6 gap-2 shrink-0">
            <Metric label="Total Return"   value={`${result.total_return_pct >= 0 ? '+' : ''}${result.total_return_pct.toFixed(2)}%`} up={result.total_return_pct >= 0} />
            <Metric label="Sharpe"         value={result.sharpe.toFixed(3)}                              up={result.sharpe >= 0} />
            <Metric label="Max Drawdown"   value={`${result.max_drawdown_pct.toFixed(2)}%`}              up={false} />
            <Metric label="Trades"         value={String(result.n_trades)} />
            <Metric label="Win Rate"       value={`${result.win_rate.toFixed(1)}%`}                      up={result.win_rate >= 50} />
            <Metric label="Profit Factor"  value={result.profit_factor.toFixed(2)}                       up={result.profit_factor >= 1} />
            <Metric label="Median Trade"   value={`${result.median_trade_return_pct >= 0 ? '+' : ''}${result.median_trade_return_pct.toFixed(2)}%`} up={result.median_trade_return_pct >= 0} />
            <Metric label="Avg Holding"    value={`${result.avg_holding_bars.toFixed(1)} bars`} />
            <Metric label="Expectancy"     value={pnlFmt(result.expectancy)}                              up={result.expectancy >= 0} />
          </div>

          {/* Benchmark comparison */}
          {result.benchmark && (
            <div className="bg-surface border border-border rounded-xl px-4 py-3 flex flex-wrap gap-x-6 gap-y-2 items-center shrink-0">
              <span className="text-[11px] text-dim uppercase tracking-wide">vs Nifty 50</span>
              <span className="text-sm text-dim">Strategy <b className="text-primary font-mono">{result.benchmark.strat_return_pct.toFixed(2)}%</b></span>
              <span className="text-sm text-dim">Nifty <b className="text-primary font-mono">{result.benchmark.bench_return_pct.toFixed(2)}%</b></span>
              <span className="text-sm text-dim">Alpha <b className={clsx('font-mono', result.benchmark.alpha_pct >= 0 ? 'text-green' : 'text-red')}>{result.benchmark.alpha_pct.toFixed(2)}%</b></span>
              <span className="text-sm text-dim">Beta <b className="text-primary font-mono">{result.benchmark.beta.toFixed(3)}</b></span>
              <span className="text-sm text-dim">Info Ratio <b className="text-primary font-mono">{result.benchmark.info_ratio.toFixed(3)}</b></span>
            </div>
          )}

          {/* Monte Carlo */}
          {result.monte_carlo && !result.monte_carlo.error && (
            <div className="bg-surface border border-border rounded-xl px-4 py-3 flex flex-wrap gap-x-6 gap-y-2 items-center shrink-0">
              <span className="text-[11px] text-dim uppercase tracking-wide">Monte Carlo (500 sims)</span>
              <span className="text-sm text-dim">Sharpe 5–95% <b className="text-primary font-mono">{result.monte_carlo.sharpe_p5.toFixed(2)} – {result.monte_carlo.sharpe_p95.toFixed(2)}</b></span>
              <span className="text-sm text-dim">Max DD 95% <b className="text-red font-mono">{result.monte_carlo.max_dd_p95.toFixed(2)}%</b></span>
              <span className="text-sm text-dim">P(Sharpe&gt;0) <b className="text-primary font-mono">{result.monte_carlo.p_value_sharpe.toFixed(1)}%</b></span>
            </div>
          )}

          {/* Walk-forward splits */}
          {wfSplits && wfSplits.length > 0 && (
            <div className="bg-surface border border-border rounded-xl p-3 shrink-0 overflow-x-auto">
              <div className="text-[11px] text-dim uppercase tracking-wide mb-2">Walk-forward — out-of-sample splits</div>
              <table className="text-sm w-full min-w-[480px]">
                <thead>
                  <tr className="text-dim text-left">
                    <th className="font-normal pb-1">Split</th>
                    <th className="font-normal pb-1">Trades</th>
                    <th className="font-normal pb-1">Win Rate</th>
                    <th className="font-normal pb-1">Return</th>
                    <th className="font-normal pb-1">Sharpe</th>
                    <th className="font-normal pb-1">Max DD</th>
                  </tr>
                </thead>
                <tbody className="font-mono">
                  {wfSplits.map(s => (
                    <tr key={s.split_index} className="border-t border-border/50">
                      <td className="py-1">{s.split_index}</td>
                      <td className="py-1">{s.n_trades}</td>
                      <td className="py-1">{s.win_rate.toFixed(1)}%</td>
                      <td className={clsx('py-1', s.total_return_pct >= 0 ? 'text-green' : 'text-red')}>
                        {s.total_return_pct >= 0 ? '+' : ''}{s.total_return_pct.toFixed(2)}%
                      </td>
                      <td className="py-1">{s.sharpe.toFixed(3)}</td>
                      <td className="py-1 text-red">{s.max_drawdown_pct.toFixed(2)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Charts */}
          <div className="flex-1 grid grid-cols-1 xl:grid-cols-[2fr_1fr] gap-3 min-h-0 overflow-hidden">

            {/* Equity curve */}
            {eqData.length > 1 && (
              <div className="bg-surface border border-border rounded-xl p-4 flex flex-col overflow-hidden">
                <div className="text-sm font-medium mb-1 text-dim uppercase tracking-wide">
                  {symbol} · {effectiveStrategy} · {period.label}
                </div>
                <div className="flex-1 min-h-0">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={eqData} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                      <defs>
                        <linearGradient id="btGrad" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%"  stopColor={eqColor} stopOpacity={0.15} />
                          <stop offset="95%" stopColor={eqColor} stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid stroke="#252d3d" strokeDasharray="3 3" vertical={false} />
                      <XAxis dataKey="i" tick={{ fill: '#8892a4', fontSize: 11 }} tickLine={false} axisLine={false} />
                      <YAxis tick={{ fill: '#8892a4', fontSize: 11 }} tickLine={false} axisLine={false}
                             width={52} tickFormatter={v => `${(v / 1000).toFixed(0)}k`} />
                      <ReferenceLine y={capital} stroke="#4b5563" strokeDasharray="4 2" />
                      <Tooltip formatter={(v: any) => [pnlFmt(Number(v)), 'Equity']} contentStyle={ttStyle} />
                      <Area type="monotone" dataKey="v" stroke={eqColor} strokeWidth={2}
                            fill="url(#btGrad)" dot={false} />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              </div>
            )}

            {/* P&L distribution */}
            {histData.length > 0 && (
              <div className="bg-surface border border-border rounded-xl p-4 flex flex-col overflow-hidden">
                <div className="text-sm font-medium mb-1 text-dim uppercase tracking-wide">P&L Distribution</div>
                <div className="flex-1 min-h-0">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={histData} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                      <CartesianGrid stroke="#252d3d" strokeDasharray="3 3" vertical={false} />
                      <XAxis dataKey="bin" tick={{ fill: '#8892a4', fontSize: 11 }} tickLine={false} axisLine={false}
                             tickFormatter={v => `${(Number(v) / 1000).toFixed(0)}k`} />
                      <YAxis tick={{ fill: '#8892a4', fontSize: 11 }} tickLine={false} axisLine={false} width={28} />
                      <ReferenceLine x={0} stroke="#4b5563" />
                      <Tooltip formatter={(v, n, p) => [v, 'Count']}
                               labelFormatter={v => `₹${Number(v).toFixed(0)}`} contentStyle={ttStyle} />
                      <Bar dataKey="count" radius={[2, 2, 0, 0]}>
                        {histData.map((d, i) => (
                          <Cell key={i} fill={d.bin >= 0 ? '#10b981' : '#f43f5e'} fillOpacity={0.8} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
            )}
          </div>

          {/* Trade log — exit reasons incl. mis_squareoff (docs/appendix/intraday-audit.md §3) */}
          {result.trades && result.trades.length > 0 && (
            <div className="bg-surface border border-border rounded-xl p-3 shrink-0 max-h-56 overflow-auto">
              <div className="text-[11px] text-dim uppercase tracking-wide mb-2 sticky top-0 bg-surface">
                Trade Log ({result.trades.length})
              </div>
              <table className="text-sm w-full min-w-[520px] font-mono">
                <thead>
                  <tr className="text-dim text-left sticky top-4 bg-surface">
                    <th className="font-normal pb-1">Dir</th>
                    <th className="font-normal pb-1">Entry</th>
                    <th className="font-normal pb-1">Exit</th>
                    <th className="font-normal pb-1">Bars</th>
                    <th className="font-normal pb-1">P&amp;L</th>
                    <th className="font-normal pb-1">Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {result.trades.map((t, i) => (
                    <tr key={i} className="border-t border-border/50">
                      <td className="py-1">{t.direction === 1 ? 'LONG' : 'SHORT'}</td>
                      <td className="py-1">₹{t.entry_price.toFixed(2)}</td>
                      <td className="py-1">₹{t.exit_price.toFixed(2)}</td>
                      <td className="py-1 text-dim">{t.entry_bar}→{t.exit_bar}</td>
                      <td className={clsx('py-1', t.pnl >= 0 ? 'text-green' : 'text-red')}>{pnlFmt(t.pnl)}</td>
                      <td className="py-1">
                        <span className={clsx('px-1.5 py-0.5 rounded text-[11px] font-bold', REASON_CLASS[t.reason] ?? 'bg-white/5 text-dim')}>
                          {t.reason}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
