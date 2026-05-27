import { useState } from 'react'
import useSWR from 'swr'
import { fetcher } from '../api'
import type { TradesResponse } from '../types'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  ReferenceLine, CartesianGrid,
} from 'recharts'
import clsx from 'clsx'

const pnlFmt = (n: number) =>
  `${n >= 0 ? '+' : '-'}₹${Math.abs(n).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`

export default function Trades() {
  const [source, setSource] = useState<'paper' | 'live'>('paper')
  const { data, isLoading } = useSWR<TradesResponse>(
    `/api/trades?source=${source}`, fetcher, { refreshInterval: 30_000 }
  )

  const trades = data?.trades ?? []
  const stats  = data?.stats

  // Histogram bins
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

  return (
    <div className="p-6 space-y-5">
      {/* Header */}
      <div className="flex items-center gap-4">
        <h1 className="text-xl font-semibold">Trade History</h1>
        <div className="flex rounded-lg border border-border overflow-hidden">
          {(['paper', 'live'] as const).map(s => (
            <button key={s} onClick={() => setSource(s)}
              className={clsx('px-4 py-1.5 text-sm capitalize transition-colors',
                source === s ? 'bg-blue text-white' : 'text-dim hover:text-primary')}>
              {s}
            </button>
          ))}
        </div>
        {isLoading && <span className="text-xs text-dim animate-pulse">Loading…</span>}
      </div>

      {/* Stats strip */}
      {stats && stats.total > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          {[
            { label: 'Total P&L',   value: pnlFmt(stats.total_pnl), up: stats.total_pnl >= 0 },
            { label: 'Win Rate',    value: `${stats.win_rate.toFixed(1)}%`, up: stats.win_rate >= 50 },
            { label: 'Avg Win',     value: pnlFmt(stats.avg_win),   up: true  },
            { label: 'Avg Loss',    value: pnlFmt(stats.avg_loss),  up: false },
            { label: 'Expectancy',  value: pnlFmt(stats.expectancy), up: stats.expectancy >= 0 },
          ].map(({ label, value, up }) => (
            <div key={label} className="bg-surface border border-border rounded-xl p-4">
              <div className="text-xs text-dim mb-1">{label}</div>
              <div className={clsx('text-lg font-mono font-medium',
                up ? 'text-green' : 'text-red')}>{value}</div>
            </div>
          ))}
        </div>
      )}

      {/* Distribution chart */}
      {histData.length > 0 && (
        <div className="bg-surface border border-border rounded-xl p-5">
          <div className="text-sm font-medium mb-4">P&L Distribution</div>
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
                  <rect key={i} fill={d.bin >= 0 ? '#10b981' : '#f43f5e'} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Table */}
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
                    <td className="px-4 py-2 text-dim whitespace-nowrap">{t.ts?.slice(0, 19)}</td>
                    <td className="px-4 py-2 font-semibold">{t.symbol}</td>
                    <td className={clsx('px-4 py-2 font-semibold',
                      t.direction === 1 ? 'text-green' : 'text-red')}>
                      {t.direction === 1 ? 'LONG' : 'SHORT'}
                    </td>
                    <td className="px-4 py-2 text-dim">{t.strategy?.slice(0, 18)}</td>
                    <td className="px-4 py-2">{t.entry_price?.toFixed(2)}</td>
                    <td className="px-4 py-2">{t.exit_price?.toFixed(2)}</td>
                    <td className="px-4 py-2">{t.size}</td>
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
