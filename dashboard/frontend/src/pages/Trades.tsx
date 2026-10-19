import { useState } from 'react'
import useSWR from 'swr'
import { fetcher } from '../api'
import type { TradesResponse, ExecutionQuality, ExecStats } from '../types'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip,
  ResponsiveContainer, ReferenceLine, CartesianGrid, Cell,
} from 'recharts'
import clsx from 'clsx'

const inr     = (n: number) => `₹${Math.abs(n).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
const pnlFmt  = (n: number) => `${n >= 0 ? '+' : '-'}${inr(n)}`
const ttStyle = { background: '#161b27', border: '1px solid #252d3d', borderRadius: 8, fontSize: 13 }

function Stat({ label, value, up }: { label: string; value: string; up?: boolean }) {
  return (
    <div className="bg-surface border border-border rounded-xl px-4 py-3">
      <div className="text-[11px] text-dim uppercase tracking-wide mb-1">{label}</div>
      <div className={clsx('text-base font-mono font-semibold',
        up === true ? 'text-green' : up === false ? 'text-red' : 'text-primary')}>
        {value}
      </div>
    </div>
  )
}

// ── Trades tab ────────────────────────────────────────────────────────────────

function TradesTab({ source }: { source: 'paper' | 'live' }) {
  const { data, isLoading } = useSWR<TradesResponse>(
    `/api/trades?source=${source}`, fetcher, { refreshInterval: 30_000 },
  )

  const trades = data?.trades ?? []
  const stats  = data?.stats

  // Strategy P&L
  const stratMap: Record<string, { pnl: number; wins: number; trades: number }> = {}
  for (const t of trades) {
    const s = t.strategy || 'unknown'
    if (!stratMap[s]) stratMap[s] = { pnl: 0, wins: 0, trades: 0 }
    stratMap[s].pnl += t.pnl; stratMap[s].trades++
    if (t.pnl > 0) stratMap[s].wins++
  }
  const stratData = Object.entries(stratMap)
    .map(([name, v]) => ({ name, pnl: v.pnl, trades: v.trades }))
    .sort((a, b) => b.pnl - a.pnl)

  // Histogram
  const pnls = trades.map(t => t.pnl)
  const histData = (() => {
    if (!pnls.length) return []
    const lo = Math.min(...pnls), hi = Math.max(...pnls)
    const step = (hi - lo) / 16 || 1
    const bins: Record<string, number> = {}
    for (const v of pnls) {
      const k = (Math.floor((v - lo) / step) * step + lo).toFixed(0)
      bins[k] = (bins[k] ?? 0) + 1
    }
    return Object.entries(bins).map(([k, c]) => ({ bin: Number(k), count: c })).sort((a, b) => a.bin - b.bin)
  })()

  const pfDisplay = !stats?.profit_factor ? '—'
    : stats.profit_factor === Infinity ? '∞'
    : stats.profit_factor.toFixed(2)

  return (
    <div className="flex flex-col flex-1 gap-3 min-h-0 overflow-hidden">
      {isLoading && <span className="text-sm text-dim animate-pulse shrink-0">Loading…</span>}

      {/* Stats */}
      {stats && stats.total > 0 && (
        <div className="grid grid-cols-4 md:grid-cols-8 gap-2 shrink-0">
          <Stat label="Total"         value={String(stats.total)} />
          <Stat label="Wins"          value={String(stats.wins)}   up={true} />
          <Stat label="Losses"        value={String(stats.losses)} up={false} />
          <Stat label="Win Rate"      value={`${stats.win_rate.toFixed(1)}%`} up={stats.win_rate >= 50} />
          <Stat label="Total P&L"     value={pnlFmt(stats.total_pnl)}         up={stats.total_pnl >= 0} />
          <Stat label="Profit Factor" value={pfDisplay}                        up={(stats.profit_factor ?? 0) >= 1} />
          <Stat label="Avg Win"       value={pnlFmt(stats.avg_win)}  up={true} />
          <Stat label="Avg Loss"      value={pnlFmt(stats.avg_loss)} up={false} />
        </div>
      )}

      {/* Charts */}
      {(stratData.length > 0 || histData.length > 0) && (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-3 shrink-0">
          {stratData.length > 0 && (
            <div className="bg-surface border border-border rounded-xl p-4">
              <div className="text-sm font-medium mb-3 text-dim uppercase tracking-wide">P&L by Strategy</div>
              <ResponsiveContainer width="100%" height={Math.min(180, Math.max(120, stratData.length * 28))}>
                <BarChart data={stratData} layout="vertical" margin={{ left: 110, right: 16, top: 0, bottom: 0 }}>
                  <CartesianGrid stroke="#252d3d" strokeDasharray="3 3" horizontal={false} />
                  <XAxis type="number" tick={{ fill: '#8892a4', fontSize: 11 }} tickLine={false} axisLine={false}
                         tickFormatter={v => `${(v / 1000).toFixed(0)}k`} />
                  <YAxis type="category" dataKey="name" tick={{ fill: '#e2e8f0', fontSize: 11 }}
                         tickLine={false} axisLine={false} width={110} />
                  <ReferenceLine x={0} stroke="#4b5563" />
                  <Tooltip formatter={(v: any) => [pnlFmt(Number(v)), 'P&L']} contentStyle={ttStyle} />
                  <Bar dataKey="pnl" radius={[0, 3, 3, 0]} maxBarSize={14}>
                    {stratData.map((d, i) => (
                      <Cell key={i} fill={d.pnl >= 0 ? '#10b981' : '#f43f5e'} fillOpacity={0.8} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {histData.length > 0 && (
            <div className="bg-surface border border-border rounded-xl p-4">
              <div className="text-sm font-medium mb-3 text-dim uppercase tracking-wide">P&L Distribution</div>
              <ResponsiveContainer width="100%" height={Math.min(180, Math.max(120, stratData.length * 28))}>
                <BarChart data={histData} margin={{ top: 0, right: 8, bottom: 0, left: 0 }}>
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
          )}
        </div>
      )}

      {/* Trade table */}
      <div className="flex-1 bg-surface border border-border rounded-xl flex flex-col min-h-0 overflow-hidden">
        <div className="px-4 py-3 border-b border-border shrink-0 flex items-center justify-between">
          <span className="text-base font-medium">
            {trades.length} {source} trade{trades.length !== 1 ? 's' : ''}
          </span>
        </div>
        {trades.length > 0 ? (
          <div className="flex-1 overflow-auto min-h-0">
            <table className="w-full text-sm font-mono min-w-[640px]">
              <thead className="sticky top-0 bg-surface z-10">
                <tr className="border-b border-border">
                  {['Date', 'Symbol', 'Side', 'Strategy', 'Entry ₹', 'Exit ₹', 'Qty', 'P&L ₹', 'Reason'].map(h => (
                    <th key={h} className="text-left px-4 py-2.5 text-[11px] uppercase tracking-wide text-dim font-medium whitespace-nowrap">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-border/50">
                {[...trades].reverse().map((t, i) => (
                  <tr key={i} className="hover:bg-white/3 transition-colors">
                    <td className="px-4 py-2 text-dim whitespace-nowrap">{t.ts?.slice(0, 10) ?? '—'}</td>
                    <td className="px-4 py-2 font-semibold">{t.symbol}</td>
                    <td className="px-4 py-2">
                      <span className={clsx('px-1.5 py-0.5 rounded text-[11px] font-bold',
                        t.direction === 1 ? 'bg-green/15 text-green' : 'bg-red/15 text-red')}>
                        {t.direction === 1 ? 'LONG' : 'SHORT'}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-dim">{t.strategy ?? '—'}</td>
                    <td className="px-4 py-2">{t.entry_price?.toFixed(2) ?? '—'}</td>
                    <td className="px-4 py-2">{t.exit_price?.toFixed(2) ?? '—'}</td>
                    <td className="px-4 py-2">{Math.round(t.size)}</td>
                    <td className={clsx('px-4 py-2 font-semibold', t.pnl >= 0 ? 'text-green' : 'text-red')}>
                      {pnlFmt(t.pnl)}
                    </td>
                    <td className="px-4 py-2 text-dim">{t.reason ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center flex-1 gap-2 text-dim">
            <span className="text-3xl opacity-30">≡</span>
            <span className="text-base">No {source} trades yet</span>
            {source === 'paper' && <code className="text-sm text-blue mt-1">python scripts/paper_trade.py</code>}
          </div>
        )}
      </div>
    </div>
  )
}

// ── Main ──────────────────────────────────────────────────────────────────────

// ── Execution quality tab ────────────────────────────────────────────────────

const bps = (v: number | null) => v === null ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(1)}`

function ExecTable({ title, rows }: { title: string; rows: (ExecStats & { key: string })[] }) {
  if (!rows.length) return null
  return (
    <div className="bg-surface border border-border rounded-xl overflow-hidden">
      <div className="px-4 py-2.5 border-b border-border text-sm font-medium text-dim uppercase tracking-wide">{title}</div>
      <table className="w-full text-sm font-mono">
        <thead><tr className="border-b border-border">
          {['', 'Orders', 'Filled', 'Avg bps', 'Median', 'P90', 'Cost'].map(h => (
            <th key={h} className="text-left px-3 py-2 text-[11px] uppercase tracking-wide text-dim font-medium">{h}</th>
          ))}
        </tr></thead>
        <tbody className="divide-y divide-border/50">
          {rows.map(r => (
            <tr key={r.key}>
              <td className="px-3 py-2">{r.key}</td>
              <td className="px-3 py-2 text-dim">{r.orders}</td>
              <td className="px-3 py-2">{r.fill_rate_pct === null ? '—' : `${r.fill_rate_pct.toFixed(0)}%`}</td>
              <td className={clsx('px-3 py-2', (r.avg_slippage_bps ?? 0) > 0 ? 'text-red' : 'text-green')}>{bps(r.avg_slippage_bps)}</td>
              <td className="px-3 py-2">{bps(r.median_slippage_bps)}</td>
              <td className="px-3 py-2">{bps(r.p90_slippage_bps)}</td>
              <td className="px-3 py-2">{inr(r.slippage_cost)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ExecutionTab({ source }: { source: 'paper' | 'live' }) {
  const [days, setDays] = useState(30)
  const { data: q, isLoading } = useSWR<ExecutionQuality>(`/api/execution/quality?days=${days}&mode=${source}`,
                                                          fetcher, { refreshInterval: 60_000 })
  return (
    <div className="flex-1 overflow-auto min-h-0 flex flex-col gap-3">
      <div className="flex items-center gap-2 text-sm">
        {[7, 30, 90].map(d => (
          <button key={d} onClick={() => setDays(d)}
                  className={clsx('px-3 py-1 rounded-lg border',
                    days === d ? 'bg-blue/15 text-blue border-blue/30' : 'border-border text-dim hover:text-primary')}>
            {d} days
          </button>
        ))}
        <span className="text-dim ml-2">Slippage vs the price the bot decided at, in basis points; + is a cost</span>
      </div>
      {isLoading && <span className="text-sm text-dim animate-pulse">Loading…</span>}
      {q && q.overall.orders === 0 && (
        <div className="bg-surface border border-border rounded-xl p-8 text-center text-dim">
          No {source} orders logged in the last {days} days (<code className="text-blue">logs/executions.jsonl</code>).
        </div>
      )}
      {q && q.overall.orders > 0 && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
            <Stat label="Orders" value={String(q.overall.orders)} />
            <Stat label="Fill rate" value={q.overall.fill_rate_pct === null ? '—' : `${q.overall.fill_rate_pct.toFixed(0)}%`} />
            <Stat label="Avg slippage" value={`${bps(q.overall.avg_slippage_bps)} bps`} up={(q.overall.avg_slippage_bps ?? 0) <= 0} />
            <Stat label="Slippage cost" value={inr(q.overall.slippage_cost)} />
            <Stat label="Outcomes" value={Object.entries(q.outcomes).map(([k, v]) => `${k} ${v}`).join(' · ')} />
          </div>
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
            <ExecTable title="Entry / exit" rows={q.by_kind} />
            <ExecTable title="Order type" rows={q.by_order_type} />
            <ExecTable title="Limit orders by chases" rows={q.by_chases} />
            <ExecTable title="Hour (IST)" rows={q.by_hour} />
          </div>
          <ExecTable title="Strategy" rows={q.by_strategy} />
        </>
      )}
    </div>
  )
}

export default function Trades() {
  const [source, setSource] = useState<'paper' | 'live'>('paper')
  const [tab, setTab] = useState<'trades' | 'execution'>('trades')

  return (
    <div className="flex flex-col h-full p-4 gap-3 overflow-hidden">
      <div className="flex items-center gap-3 shrink-0">
        <h1 className="text-lg font-semibold tracking-wide">Trade History</h1>
        <div className="flex rounded-lg border border-border overflow-hidden">
          {(['paper', 'live'] as const).map(s => (
            <button key={s} onClick={() => setSource(s)}
              className={clsx('px-4 py-2 text-sm capitalize transition-colors',
                source === s ? 'bg-blue text-white font-medium' : 'text-dim hover:text-primary')}>
              {s}
            </button>
          ))}
        </div>
        <div className="ml-auto flex gap-1.5">
          {(['trades', 'execution'] as const).map(t => (
            <button key={t} onClick={() => setTab(t)}
              className={clsx('px-3 py-1.5 rounded-lg text-sm transition-colors',
                tab === t ? 'bg-blue/15 text-blue border border-blue/30 font-medium'
                          : 'bg-surface border border-border text-dim hover:text-primary')}>
              {t === 'trades' ? 'Trades' : 'Execution quality'}
            </button>
          ))}
        </div>
      </div>
      {tab === 'trades' ? <TradesTab source={source} /> : <ExecutionTab source={source} />}
    </div>
  )
}
