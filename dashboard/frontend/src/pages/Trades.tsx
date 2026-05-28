import { useState } from 'react'
import useSWR from 'swr'
import { fetcher } from '../api'
import type { TradesResponse } from '../types'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  ReferenceLine, CartesianGrid, Cell,
} from 'recharts'
import clsx from 'clsx'

const pnlFmt = (n: number) =>
  `${n >= 0 ? '+' : '-'}₹${Math.abs(n).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`

export default function Trades() {
  const [source, setSource] = useState<'paper' | 'live'>('paper')
  const { data, isLoading } = useSWR<TradesResponse>(
    `/api/trades?source=${source}`, fetcher, { refreshInterval: 30_000 },
  )

  const trades = data?.trades ?? []
  const stats  = data?.stats

  // ── P&L distribution histogram ────────────────────────────────────────────

  const pnls = trades.map(t => t.pnl).filter(Boolean)
  const histData = (() => {
    if (!pnls.length) return []
    const min = Math.min(...pnls), max = Math.max(...pnls)
    const bins = 20
    const step = (max - min) / bins || 1
    const counts: Record<string, number> = {}
    for (const v of pnls) {
      const b = Math.floor((v - min) / step) * step + min
      const k = b.toFixed(0)
      counts[k] = (counts[k] ?? 0) + 1
    }
    return Object.entries(counts)
      .map(([k, count]) => ({ bin: Number(k), count }))
      .sort((a, b) => a.bin - b.bin)
  })()

  // ── Strategy P&L aggregation ──────────────────────────────────────────────

  const stratMap: Record<string, { pnl: number; wins: number; trades: number }> = {}
  for (const t of trades) {
    const s = t.strategy || 'unknown'
    if (!stratMap[s]) stratMap[s] = { pnl: 0, wins: 0, trades: 0 }
    stratMap[s].pnl    += t.pnl
    stratMap[s].trades += 1
    if (t.pnl > 0) stratMap[s].wins++
  }
  const stratData = Object.entries(stratMap)
    .map(([name, v]) => ({ name, pnl: v.pnl, trades: v.trades, wins: v.wins }))
    .sort((a, b) => b.pnl - a.pnl)

  // ── Profit factor ─────────────────────────────────────────────────────────

  const pfDisplay = stats?.profit_factor
    ? (stats.profit_factor === 0 ? '—' : stats.profit_factor.toFixed(2))
    : '—'

  return (
    <div className="p-6 space-y-5">
      {/* Header */}
      <div className="flex items-center gap-4">
        <h1 className="text-xl font-semibold">Trade History</h1>
        <div className="flex rounded-lg border border-border overflow-hidden">
          {(['paper', 'live'] as const).map(s => (
            <button
              key={s}
              onClick={() => setSource(s)}
              className={clsx(
                'px-4 py-1.5 text-sm capitalize transition-colors',
                source === s ? 'bg-blue text-white' : 'text-dim hover:text-primary',
              )}>
              {s}
            </button>
          ))}
        </div>
        {isLoading && <span className="text-xs text-dim animate-pulse">Loading…</span>}
      </div>

      {/* Stats strip */}
      {stats && stats.total > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-8 gap-3">
          {[
            { label: 'Total',      value: String(stats.total),               up: undefined },
            { label: 'Wins',       value: String(stats.wins),                up: true },
            { label: 'Losses',     value: String(stats.losses),              up: false },
            { label: 'Win Rate',   value: `${stats.win_rate.toFixed(1)}%`,   up: stats.win_rate >= 50 },
            { label: 'Total P&L',  value: pnlFmt(stats.total_pnl),          up: stats.total_pnl >= 0 },
            { label: 'Profit Factor', value: pfDisplay,                      up: stats.profit_factor >= 1 },
            { label: 'Avg Win',    value: pnlFmt(stats.avg_win),             up: true },
            { label: 'Avg Loss',   value: pnlFmt(stats.avg_loss),            up: false },
          ].map(({ label, value, up }) => (
            <div key={label} className="bg-surface border border-border rounded-xl p-4">
              <div className="text-xs text-dim mb-1">{label}</div>
              <div className={clsx(
                'text-base font-mono font-medium',
                up === true ? 'text-green' : up === false ? 'text-red' : 'text-primary',
              )}>
                {value}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Win/Loss by strategy + P&L distribution */}
      {(stratData.length > 0 || histData.length > 0) && (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          {/* Win/Loss by strategy */}
          {stratData.length > 0 && (
            <div className="bg-surface border border-border rounded-xl p-5">
              <div className="text-sm font-medium mb-4">Net P&L by Strategy</div>
              <ResponsiveContainer width="100%" height={Math.max(180, stratData.length * 32)}>
                <BarChart data={stratData} layout="vertical" margin={{ left: 130, right: 20 }}>
                  <CartesianGrid stroke="#252d3d" strokeDasharray="3 3" />
                  <XAxis
                    type="number"
                    tick={{ fill: '#8892a4', fontSize: 10 }}
                    tickFormatter={v => `₹${(v / 1000).toFixed(0)}k`}
                  />
                  <YAxis
                    type="category"
                    dataKey="name"
                    tick={{ fill: '#e2e8f0', fontSize: 10 }}
                    width={130}
                  />
                  <ReferenceLine x={0} stroke="#4b5563" />
                  <Tooltip
                    formatter={(v: any) => [pnlFmt(Number(v)), 'P&L']}
                    contentStyle={{ background: '#161b27', border: '1px solid #252d3d', borderRadius: 8, fontSize: 12 }}
                  />
                  <Bar dataKey="pnl" radius={[0, 4, 4, 0]}>
                    {stratData.map((d, i) => (
                      <Cell key={i} fill={d.pnl >= 0 ? '#10b981' : '#f43f5e'} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* P&L distribution */}
          {histData.length > 0 && (
            <div className="bg-surface border border-border rounded-xl p-5">
              <div className="text-sm font-medium mb-4">P&L Distribution</div>
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={histData}>
                  <CartesianGrid stroke="#252d3d" strokeDasharray="3 3" />
                  <XAxis
                    dataKey="bin"
                    tick={{ fill: '#8892a4', fontSize: 10 }}
                    tickFormatter={v => `₹${Number(v).toFixed(0)}`}
                  />
                  <YAxis tick={{ fill: '#8892a4', fontSize: 10 }} />
                  <ReferenceLine x={0} stroke="#4b5563" />
                  <Tooltip
                    formatter={(v: any) => [v, 'Count']}
                    labelFormatter={v => `₹${Number(v).toFixed(0)}`}
                    contentStyle={{ background: '#161b27', border: '1px solid #252d3d', borderRadius: 8, fontSize: 12 }}
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

      {/* Trade table */}
      <div className="bg-surface border border-border rounded-xl overflow-hidden">
        <div className="px-5 py-3 border-b border-border text-sm font-medium">
          {trades.length} trades
        </div>
        {trades.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-xs font-mono">
              <thead>
                <tr className="text-dim border-b border-border">
                  {['Time', 'Symbol', 'Side', 'Strategy', 'Entry ₹', 'Exit ₹', 'Qty', 'P&L ₹', 'Reason'].map(h => (
                    <th key={h} className="text-left px-4 py-2.5 font-medium whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {[...trades].reverse().map((t, i) => (
                  <tr key={i} className="hover:bg-border/20 transition-colors">
                    <td className="px-4 py-2 text-dim whitespace-nowrap">{t.ts?.slice(0, 10)}</td>
                    <td className="px-4 py-2 font-semibold">{t.symbol}</td>
                    <td className={clsx('px-4 py-2 font-semibold',
                      t.direction === 1 ? 'text-green' : 'text-red')}>
                      <span className={clsx(
                        'px-1.5 py-0.5 rounded text-xs',
                        t.direction === 1 ? 'bg-green/10' : 'bg-red/10',
                      )}>
                        {t.direction === 1 ? 'LONG' : 'SHORT'}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-dim">{t.strategy?.slice(0, 18)}</td>
                    <td className="px-4 py-2">{t.entry_price?.toFixed(2)}</td>
                    <td className="px-4 py-2">{t.exit_price?.toFixed(2)}</td>
                    <td className="px-4 py-2">{Math.round(t.size)}</td>
                    <td className={clsx('px-4 py-2 font-semibold',
                      t.pnl >= 0 ? 'text-green' : 'text-red')}>
                      {pnlFmt(t.pnl)}
                    </td>
                    <td className="px-4 py-2 text-dim">{t.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="px-5 py-10 text-center text-dim text-sm">
            No {source} trades yet.
          </div>
        )}
      </div>
    </div>
  )
}
