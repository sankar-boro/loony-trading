import { useState } from 'react'
import useSWR from 'swr'
import { fetcher } from '../api'
import type { TradesResponse } from '../types'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  ReferenceLine, CartesianGrid, Cell,
} from 'recharts'
import clsx from 'clsx'

const inr    = (n: number) => `₹${Math.abs(n).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
const pnlFmt = (n: number) => `${n >= 0 ? '+' : '-'}${inr(n)}`
const ttStyle = { background: '#161b27', border: '1px solid #252d3d', borderRadius: 8, fontSize: 11 }

function Stat({ label, value, up }: { label: string; value: string; up?: boolean }) {
  return (
    <div className="bg-surface border border-border rounded-xl px-4 py-3">
      <div className="text-[9px] text-dim uppercase tracking-wide mb-1">{label}</div>
      <div className={clsx('text-sm font-mono font-semibold',
        up === true ? 'text-green' : up === false ? 'text-red' : 'text-primary')}>
        {value}
      </div>
    </div>
  )
}

export default function Trades() {
  const [source, setSource] = useState<'paper' | 'live'>('paper')
  const { data, isLoading } = useSWR<TradesResponse>(
    `/api/trades?source=${source}`, fetcher, { refreshInterval: 30_000 },
  )

  const trades = data?.trades ?? []
  const stats  = data?.stats

  // Strategy P&L aggregation
  const stratMap: Record<string, { pnl: number; wins: number; trades: number }> = {}
  for (const t of trades) {
    const s = t.strategy || 'unknown'
    if (!stratMap[s]) stratMap[s] = { pnl: 0, wins: 0, trades: 0 }
    stratMap[s].pnl += t.pnl
    stratMap[s].trades++
    if (t.pnl > 0) stratMap[s].wins++
  }
  const stratData = Object.entries(stratMap)
    .map(([name, v]) => ({ name, pnl: v.pnl, trades: v.trades }))
    .sort((a, b) => b.pnl - a.pnl)

  // P&L histogram
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

  const pfDisplay = stats?.profit_factor
    ? (stats.profit_factor === Infinity ? '∞' : stats.profit_factor.toFixed(2))
    : '—'

  return (
    <div className="flex flex-col h-full p-4 gap-3 overflow-hidden">

      {/* Header */}
      <div className="flex items-center gap-3 shrink-0">
        <h1 className="text-base font-semibold tracking-wide">Trade History</h1>
        <div className="flex rounded-lg border border-border overflow-hidden ml-2">
          {(['paper', 'live'] as const).map(s => (
            <button key={s} onClick={() => setSource(s)}
              className={clsx('px-4 py-1.5 text-xs capitalize transition-colors',
                source === s ? 'bg-blue text-white' : 'text-dim hover:text-primary')}>
              {s}
            </button>
          ))}
        </div>
        {isLoading && <span className="text-xs text-dim animate-pulse">Loading…</span>}
      </div>

      {/* Stats strip */}
      {stats && stats.total > 0 && (
        <div className="grid grid-cols-4 md:grid-cols-8 gap-2 shrink-0">
          <Stat label="Total"         value={String(stats.total)} />
          <Stat label="Wins"          value={String(stats.wins)}   up={true} />
          <Stat label="Losses"        value={String(stats.losses)} up={false} />
          <Stat label="Win Rate"      value={`${stats.win_rate.toFixed(1)}%`} up={stats.win_rate >= 50} />
          <Stat label="Total P&L"     value={pnlFmt(stats.total_pnl)}         up={stats.total_pnl >= 0} />
          <Stat label="Profit Factor" value={pfDisplay}                        up={stats.profit_factor >= 1} />
          <Stat label="Avg Win"       value={pnlFmt(stats.avg_win)}  up={true} />
          <Stat label="Avg Loss"      value={pnlFmt(stats.avg_loss)} up={false} />
        </div>
      )}

      {/* Charts + table */}
      <div className="flex-1 grid grid-cols-1 xl:grid-rows-[220px_1fr] gap-3 min-h-0 overflow-hidden">

        {/* Charts row */}
        {(stratData.length > 0 || histData.length > 0) && (
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-3 shrink-0">

            {/* Strategy P&L */}
            {stratData.length > 0 && (
              <div className="bg-surface border border-border rounded-xl p-4 flex flex-col">
                <div className="text-xs font-medium mb-3 text-dim uppercase tracking-wide">P&L by Strategy</div>
                <div className="flex-1 min-h-0">
                  <ResponsiveContainer width="100%" height={160}>
                    <BarChart data={stratData} layout="vertical" margin={{ left: 110, right: 16, top: 0, bottom: 0 }}>
                      <CartesianGrid stroke="#252d3d" strokeDasharray="3 3" horizontal={false} />
                      <XAxis type="number" tick={{ fill: '#8892a4', fontSize: 9 }} tickLine={false} axisLine={false}
                             tickFormatter={v => `${(v / 1000).toFixed(0)}k`} />
                      <YAxis type="category" dataKey="name" tick={{ fill: '#e2e8f0', fontSize: 9 }}
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
              </div>
            )}

            {/* P&L distribution */}
            {histData.length > 0 && (
              <div className="bg-surface border border-border rounded-xl p-4 flex flex-col">
                <div className="text-xs font-medium mb-3 text-dim uppercase tracking-wide">P&L Distribution</div>
                <div className="flex-1 min-h-0">
                  <ResponsiveContainer width="100%" height={160}>
                    <BarChart data={histData} margin={{ top: 0, right: 8, bottom: 0, left: 0 }}>
                      <CartesianGrid stroke="#252d3d" strokeDasharray="3 3" vertical={false} />
                      <XAxis dataKey="bin" tick={{ fill: '#8892a4', fontSize: 9 }} tickLine={false} axisLine={false}
                             tickFormatter={v => `${(Number(v) / 1000).toFixed(0)}k`} />
                      <YAxis tick={{ fill: '#8892a4', fontSize: 9 }} tickLine={false} axisLine={false} width={28} />
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
        )}

        {/* Trade table */}
        <div className="bg-surface border border-border rounded-xl flex flex-col min-h-0 overflow-hidden">
          <div className="px-4 py-3 border-b border-border flex items-center justify-between shrink-0">
            <span className="text-sm font-medium">
              {trades.length} {source} trade{trades.length !== 1 ? 's' : ''}
            </span>
          </div>

          {trades.length > 0 ? (
            <div className="flex-1 overflow-auto min-h-0">
              <table className="w-full text-xs font-mono min-w-[640px]">
                <thead className="sticky top-0 bg-surface z-10">
                  <tr className="border-b border-border">
                    {['Date', 'Symbol', 'Side', 'Strategy', 'Entry ₹', 'Exit ₹', 'Qty', 'P&L ₹', 'Reason'].map(h => (
                      <th key={h} className="text-left px-4 py-2.5 text-[9px] uppercase tracking-wide text-dim font-medium whitespace-nowrap">
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
                        <span className={clsx(
                          'px-1.5 py-0.5 rounded text-[9px] font-bold',
                          t.direction === 1 ? 'bg-green/15 text-green' : 'bg-red/15 text-red',
                        )}>
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
              <span className="text-2xl opacity-30">≡</span>
              <span className="text-sm">No {source} trades yet</span>
              {source === 'paper' && (
                <code className="text-xs text-blue mt-1">python scripts/paper_trade.py</code>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
