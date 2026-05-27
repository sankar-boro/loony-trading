import { useState, useEffect } from 'react'
import { api } from '../api'
import type { BacktestResult, ConfigResponse } from '../types'
import useSWR from 'swr'
import { fetcher } from '../api'
import {
  AreaChart, Area, BarChart, Bar, XAxis, YAxis, Tooltip,
  ResponsiveContainer, ReferenceLine, CartesianGrid, Cell,
} from 'recharts'
import clsx from 'clsx'

const SYMBOLS  = ['RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'ICICIBANK', 'SBIN', 'AXISBANK', 'NIFTY50']
const PERIODS  = [
  { label: '3 months', days: 90  },
  { label: '6 months', days: 180 },
  { label: '1 year',   days: 365 },
]
const fmt = (n: number) =>
  `${n >= 0 ? '+' : '-'}₹${Math.abs(n).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`

export default function Backtest() {
  const { data: cfg } = useSWR<ConfigResponse>('/api/config', fetcher)

  const [symbol,   setSymbol]   = useState('NIFTY50')
  const [strategy, setStrategy] = useState('')
  const [period,   setPeriod]   = useState(PERIODS[1])
  const [capital,  setCapital]  = useState(500_000)
  const [jobId,    setJobId]    = useState<string | null>(null)
  const [status,   setStatus]   = useState<'idle' | 'running' | 'done' | 'error'>('idle')
  const [result,   setResult]   = useState<BacktestResult | null>(null)
  const [errMsg,   setErrMsg]   = useState('')

  const strategies = cfg?.enabled ?? []
  const effectiveStrategy = strategy || strategies[0] || 'ema_crossover'

  // Poll job status
  useEffect(() => {
    if (!jobId || status !== 'running') return
    const id = setInterval(async () => {
      try {
        const r = await api.pollBacktest(jobId)
        if (r.status === 'done') {
          setStatus('done')
          setResult(r.result ?? null)
          clearInterval(id)
        } else if (r.status === 'error') {
          setStatus('error')
          setErrMsg(r.error ?? 'Unknown error')
          clearInterval(id)
        }
      } catch {}
    }, 1_500)
    return () => clearInterval(id)
  }, [jobId, status])

  const run = async () => {
    setStatus('running')
    setResult(null)
    setErrMsg('')
    try {
      const { job_id } = await api.submitBacktest({
        symbol, strategy: effectiveStrategy, days: period.days, capital,
      })
      setJobId(job_id)
    } catch (e: any) {
      setStatus('error')
      setErrMsg(e.message)
    }
  }

  // Equity chart data
  const eqData = result?.equity_curve.map((v, i) => ({ i, equity: v })) ?? []
  const histData = (() => {
    if (!result?.trades_pnl.length) return []
    const pnls = result.trades_pnl
    const min = Math.min(...pnls), max = Math.max(...pnls)
    const bins = 20, step = (max - min) / bins || 1
    const counts: Record<string, number> = {}
    for (const v of pnls) {
      const b = Math.floor((v - min) / step) * step + min
      const k = b.toFixed(0)
      counts[k] = (counts[k] ?? 0) + 1
    }
    return Object.entries(counts).map(([k, c]) => ({ bin: Number(k), count: c })).sort((a, b) => a.bin - b.bin)
  })()

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-xl font-semibold">Backtest</h1>

      {/* Controls */}
      <div className="bg-surface border border-border rounded-xl p-5 flex flex-wrap gap-4 items-end">
        <div className="space-y-1.5">
          <label className="text-xs text-dim">Symbol</label>
          <select value={symbol} onChange={e => setSymbol(e.target.value)}
            className="bg-bg border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue">
            {SYMBOLS.map(s => <option key={s}>{s}</option>)}
          </select>
        </div>
        <div className="space-y-1.5">
          <label className="text-xs text-dim">Strategy</label>
          <select value={effectiveStrategy} onChange={e => setStrategy(e.target.value)}
            className="bg-bg border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue">
            {(strategies.length ? strategies : ['ema_crossover']).map(s => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </div>
        <div className="space-y-1.5">
          <label className="text-xs text-dim">Period</label>
          <div className="flex rounded-lg border border-border overflow-hidden">
            {PERIODS.map(p => (
              <button key={p.days} onClick={() => setPeriod(p)}
                className={clsx('px-3 py-2 text-sm transition-colors',
                  period.days === p.days ? 'bg-blue text-white' : 'text-dim hover:text-primary')}>
                {p.label}
              </button>
            ))}
          </div>
        </div>
        <div className="space-y-1.5">
          <label className="text-xs text-dim">Capital ₹</label>
          <input
            type="number"
            value={capital}
            onChange={e => setCapital(Number(e.target.value))}
            step={50000}
            className="bg-bg border border-border rounded-lg px-3 py-2 text-sm w-36 focus:outline-none focus:border-blue"
          />
        </div>
        <button
          onClick={run}
          disabled={status === 'running'}
          className="px-6 py-2 rounded-lg bg-blue text-white text-sm font-medium
                     hover:bg-blue/80 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {status === 'running' ? (
            <span className="flex items-center gap-2">
              <span className="inline-block w-3 h-3 rounded-full border-2 border-white/30 border-t-white animate-spin" />
              Running…
            </span>
          ) : '▶ Run Backtest'}
        </button>
      </div>

      {/* Error */}
      {status === 'error' && (
        <div className="bg-red/10 border border-red/30 rounded-xl px-5 py-4 text-sm text-red">
          {errMsg}
        </div>
      )}

      {/* Results */}
      {result && (
        <div className="space-y-5">
          {/* Metrics */}
          <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
            {[
              { label: 'Total Return',   value: `${result.total_return_pct >= 0 ? '+' : ''}${result.total_return_pct.toFixed(2)}%`, up: result.total_return_pct >= 0 },
              { label: 'Sharpe',         value: result.sharpe.toFixed(3),          up: result.sharpe >= 0 },
              { label: 'Max Drawdown',   value: `${result.max_drawdown_pct.toFixed(2)}%`, up: false },
              { label: 'Trades',         value: String(result.n_trades),            up: undefined },
              { label: 'Win Rate',       value: `${result.win_rate.toFixed(1)}%`,  up: result.win_rate >= 50 },
              { label: 'Profit Factor',  value: result.profit_factor.toFixed(2),   up: result.profit_factor >= 1 },
            ].map(({ label, value, up }) => (
              <div key={label} className="bg-surface border border-border rounded-xl p-4">
                <div className="text-xs text-dim mb-1">{label}</div>
                <div className={clsx('text-xl font-mono font-medium',
                  up === true ? 'text-green' : up === false ? 'text-red' : '')}>{value}</div>
              </div>
            ))}
          </div>

          {/* Equity curve */}
          {eqData.length > 1 && (
            <div className="bg-surface border border-border rounded-xl p-5">
              <div className="text-sm font-medium mb-4">
                {symbol} — {effectiveStrategy} — {period.label}
              </div>
              <ResponsiveContainer width="100%" height={260}>
                <AreaChart data={eqData}>
                  <defs>
                    <linearGradient id="btGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%"  stopColor="#10b981" stopOpacity={0.15} />
                      <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke="#252d3d" strokeDasharray="3 3" />
                  <XAxis dataKey="i" tick={{ fill: '#8892a4', fontSize: 10 }} />
                  <YAxis tick={{ fill: '#8892a4', fontSize: 10 }}
                         tickFormatter={v => `₹${(v/1000).toFixed(0)}k`} />
                  <ReferenceLine y={capital} stroke="#8892a4" strokeDasharray="4 4" />
                  <Tooltip
                    formatter={(v: any) => [fmt(Number(v)), 'Equity']}
                    contentStyle={{ background: '#161b27', border: '1px solid #252d3d', borderRadius: 8, fontSize: 12 }}
                  />
                  <Area type="monotone" dataKey="equity" stroke="#10b981" strokeWidth={2}
                        fill="url(#btGrad)" dot={false} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Distribution */}
          {histData.length > 0 && (
            <div className="bg-surface border border-border rounded-xl p-5">
              <div className="text-sm font-medium mb-4">Trade P&L Distribution</div>
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={histData}>
                  <CartesianGrid stroke="#252d3d" strokeDasharray="3 3" />
                  <XAxis dataKey="bin" tick={{ fill: '#8892a4', fontSize: 10 }}
                         tickFormatter={v => `₹${Number(v).toFixed(0)}`} />
                  <YAxis tick={{ fill: '#8892a4', fontSize: 10 }} />
                  <ReferenceLine x={0} stroke="#4b5563" />
                  <Tooltip
                    formatter={(v, n, props) => [v, 'Count']}
                    labelFormatter={v => `₹${Number(v).toFixed(0)}`}
                    contentStyle={{ background: '#161b27', border: '1px solid #252d3d', borderRadius: 8 }}
                  />
                  <Bar dataKey="count" radius={[3, 3, 0, 0]}>
                    {histData.map((d, i) => (
                      <Cell key={i} fill={d.bin >= 0 ? '#10b981' : '#f43f5e'} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
