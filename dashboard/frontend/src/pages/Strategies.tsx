import { Fragment, useState } from 'react'
import useSWR from 'swr'
import { fetcher } from '../api'
import type { ConfigResponse, TradesResponse } from '../types'
import {
  BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine, CartesianGrid,
} from 'recharts'
import clsx from 'clsx'

const inr    = (n: number) => `₹${Math.abs(n).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
const pnlFmt = (n: number) => `${n >= 0 ? '+' : '-'}${inr(n)}`
const ttStyle = { background: '#161b27', border: '1px solid #252d3d', borderRadius: 8, fontSize: 13 }

const COLORS = [
  '#3b82f6', '#10b981', '#f59e0b', '#f43f5e', '#8b5cf6',
  '#06b6d4', '#ec4899', '#84cc16', '#f97316', '#6366f1',
  '#14b8a6', '#a855f7',
]

export default function Strategies() {
  const { data: cfg }    = useSWR<ConfigResponse>('/api/config',  fetcher, { refreshInterval: 300_000 })
  const { data: trades } = useSWR<TradesResponse>('/api/trades?source=paper', fetcher, { refreshInterval: 60_000 })

  const weights  = cfg?.weights ?? {}
  const enabled  = new Set(cfg?.enabled ?? [])
  const allNames = Array.from(new Set([...Object.keys(weights), ...(cfg?.all_strategies ?? [])])).sort()
  const maxW     = Math.max(...Object.values(weights), 1)
  const params   = cfg?.params ?? {}
  const [open, setOpen] = useState<string | null>(null)

  // Per-strategy trade aggregation
  const stratMap: Record<string, { trades: number; wins: number; total_pnl: number }> = {}
  for (const t of (trades?.trades ?? [])) {
    const s = t.strategy || 'unknown'
    if (!stratMap[s]) stratMap[s] = { trades: 0, wins: 0, total_pnl: 0 }
    stratMap[s].trades++
    stratMap[s].total_pnl += t.pnl
    if (t.pnl > 0) stratMap[s].wins++
  }
  const stratStats = Object.entries(stratMap)
    .map(([name, s]) => ({
      name,
      trades:   s.trades,
      wins:     s.wins,
      win_rate: s.trades ? s.wins / s.trades * 100 : 0,
      total_pnl: s.total_pnl,
      avg_pnl:  s.trades ? s.total_pnl / s.trades : 0,
    }))
    .sort((a, b) => b.total_pnl - a.total_pnl)

  const donutData = Object.entries(weights)
    .filter(([, w]) => w > 0)
    .map(([name, value]) => ({ name, value }))
    .sort((a, b) => b.value - a.value)

  return (
    <div className="flex flex-col h-full p-4 gap-3 overflow-hidden">

      {/* Header */}
      <div className="flex items-center justify-between shrink-0">
        <h1 className="text-lg font-semibold tracking-wide">Strategies</h1>
        <span className="text-sm text-dim">
          tune: <code className="text-blue">python scripts/tune_weights.py</code>
        </span>
      </div>

      {/* Top row: donut + weights table */}
      <div className="grid grid-cols-1 xl:grid-cols-[240px_1fr] gap-3 shrink-0" style={{ maxHeight: 280 }}>

        {/* Allocation donut */}
        <div className="bg-surface border border-border rounded-xl p-4 flex flex-col">
          <div className="text-sm font-medium mb-2 text-dim uppercase tracking-wide">Allocation</div>
          {donutData.length > 0 ? (
            <>
              <ResponsiveContainer width="100%" height={120}>
                <PieChart>
                  <Pie data={donutData} cx="50%" cy="50%"
                       innerRadius={38} outerRadius={55}
                       paddingAngle={2} dataKey="value">
                    {donutData.map((_, i) => (
                      <Cell key={i} fill={COLORS[i % COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip formatter={(v: any, name: any) => [`${Number(v).toFixed(2)}`, name]}
                           contentStyle={ttStyle} />
                </PieChart>
              </ResponsiveContainer>
              <div className="space-y-1 overflow-y-auto flex-1">
                {donutData.map((d, i) => (
                  <div key={d.name} className="flex items-center gap-2 text-[12px] font-mono">
                    <span className="w-2 h-2 rounded-full shrink-0" style={{ background: COLORS[i % COLORS.length] }} />
                    <span className="text-dim truncate flex-1">{d.name}</span>
                    <span className="text-primary">{d.value.toFixed(2)}</span>
                  </div>
                ))}
              </div>
            </>
          ) : (
            <div className="flex-1 flex items-center justify-center text-sm text-dim">No weights</div>
          )}
        </div>

        {/* Weights table */}
        <div className="bg-surface border border-border rounded-xl flex flex-col overflow-hidden">
          <div className="px-4 py-3 border-b border-border flex items-center justify-between shrink-0">
            <span className="text-base font-medium">All Strategies</span>
            <span className="text-sm text-dim">{enabled.size} enabled / {allNames.length} total</span>
          </div>
          <div className="flex-1 overflow-y-auto min-h-0">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-surface z-10 border-b border-border">
                <tr>
                  {['Strategy', 'Weight', '', 'Status'].map(h => (
                    <th key={h} className="text-left px-4 py-2 text-[11px] uppercase tracking-wide text-dim font-medium">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-border/50">
                {allNames.map(name => {
                  const w = weights[name] ?? 0
                  const on = enabled.has(name)
                  const p = params[name]
                  return (
                    <Fragment key={name}>
                    <tr className={clsx('hover:bg-white/3 transition-colors', p && 'cursor-pointer')}
                        onClick={() => p && setOpen(open === name ? null : name)}
                        title={p ? 'Show parameters' : undefined}>
                      <td className="px-4 py-2 font-mono">
                        {p && <span className="text-dim mr-1.5 text-[11px]">{open === name ? '▾' : '▸'}</span>}
                        {name}
                      </td>
                      <td className="px-4 py-2 font-mono text-dim w-14">{w.toFixed(2)}</td>
                      <td className="px-4 py-2 w-32">
                        <div className="h-1.5 rounded-full bg-border overflow-hidden">
                          <div className="h-full rounded-full bg-blue/60"
                               style={{ width: `${(w / maxW) * 100}%` }} />
                        </div>
                      </td>
                      <td className="px-4 py-2">
                        <span className={clsx(
                          'inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium',
                          on ? 'bg-green/10 text-green' : 'bg-border text-dim',
                        )}>
                          <span className={clsx('w-1.5 h-1.5 rounded-full', on ? 'bg-green' : 'bg-muted')} />
                          {on ? 'enabled' : 'off'}
                        </span>
                      </td>
                    </tr>
                    {open === name && p && (
                      <tr className="bg-white/[0.02]">
                        <td colSpan={4} className="px-4 py-2.5">
                          <div className="flex flex-wrap gap-1.5">
                            {Object.entries(p).map(([k, v]) => (
                              <span key={k} className="font-mono text-[12px] px-2 py-0.5 rounded bg-border/70">
                                <span className="text-dim">{k}</span> {String(v)}
                              </span>
                            ))}
                          </div>
                          <div className="text-[11px] text-dim mt-1.5">
                            Override in <code className="text-blue">config/settings.yaml</code> under{' '}
                            <code className="text-blue">strategies.params.{name}</code>
                          </div>
                        </td>
                      </tr>
                    )}
                    </Fragment>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* Performance section */}
      {stratStats.length > 0 ? (
        <div className="flex-1 grid grid-cols-1 xl:grid-cols-[1fr_360px] gap-3 min-h-0 overflow-hidden">

          {/* Horizontal bar chart */}
          <div className="bg-surface border border-border rounded-xl p-4 flex flex-col overflow-hidden">
            <div className="text-sm font-medium mb-3 text-dim uppercase tracking-wide">Net P&L by Strategy</div>
            <div className="flex-1 min-h-0 overflow-y-auto">
              <ResponsiveContainer width="100%" height={Math.max(160, stratStats.length * 30)}>
                <BarChart data={stratStats} layout="vertical" margin={{ left: 120, right: 20, top: 0, bottom: 0 }}>
                  <CartesianGrid stroke="#252d3d" strokeDasharray="3 3" horizontal={false} />
                  <XAxis type="number" tick={{ fill: '#8892a4', fontSize: 11 }} tickLine={false} axisLine={false}
                         tickFormatter={v => `${(v / 1000).toFixed(0)}k`} />
                  <YAxis type="category" dataKey="name" tick={{ fill: '#e2e8f0', fontSize: 11 }}
                         tickLine={false} axisLine={false} width={120} />
                  <ReferenceLine x={0} stroke="#4b5563" />
                  <Tooltip formatter={(v: any) => [pnlFmt(Number(v)), 'P&L']} contentStyle={ttStyle} />
                  <Bar dataKey="total_pnl" radius={[0, 3, 3, 0]} maxBarSize={16}>
                    {stratStats.map((s, i) => (
                      <Cell key={i} fill={s.total_pnl >= 0 ? '#10b981' : '#f43f5e'} fillOpacity={0.8} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Per-strategy table */}
          <div className="bg-surface border border-border rounded-xl flex flex-col overflow-hidden">
            <div className="px-4 py-3 border-b border-border shrink-0">
              <span className="text-base font-medium">Performance</span>
            </div>
            <div className="flex-1 overflow-y-auto min-h-0">
              <table className="w-full text-sm font-mono">
                <thead className="sticky top-0 bg-surface z-10 border-b border-border">
                  <tr>
                    {['Strategy', 'N', 'Win%', 'P&L'].map(h => (
                      <th key={h} className="text-left px-4 py-2 text-[11px] uppercase tracking-wide text-dim font-medium">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/50">
                  {stratStats.map((s, i) => (
                    <tr key={i} className="hover:bg-white/3 transition-colors">
                      <td className="px-4 py-2.5 truncate max-w-[130px]">{s.name}</td>
                      <td className="px-4 py-2.5 text-dim">{s.trades}</td>
                      <td className={clsx('px-4 py-2.5', s.win_rate >= 50 ? 'text-green' : 'text-red')}>
                        {s.win_rate.toFixed(0)}%
                      </td>
                      <td className={clsx('px-4 py-2.5 font-semibold', s.total_pnl >= 0 ? 'text-green' : 'text-red')}>
                        {pnlFmt(s.total_pnl)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      ) : (
        <div className="flex-1 bg-surface border border-border rounded-xl flex flex-col items-center justify-center gap-2 text-dim">
          <span className="text-4xl opacity-20">◇</span>
          <span className="text-base">No trade data yet</span>
          <code className="text-sm text-blue mt-1">python scripts/paper_trade.py</code>
        </div>
      )}
    </div>
  )
}
