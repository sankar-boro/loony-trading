import useSWR from 'swr'
import { fetcher } from '../api'
import type { ConfigResponse, TradesResponse } from '../types'
import {
  BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine, CartesianGrid,
} from 'recharts'
import clsx from 'clsx'

const fmt = (n: number) =>
  `${n >= 0 ? '+' : '-'}₹${Math.abs(n).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`

const CHART_COLORS = [
  '#3b82f6', '#10b981', '#f59e0b', '#f43f5e', '#8b5cf6',
  '#06b6d4', '#ec4899', '#84cc16', '#f97316', '#6366f1',
]

export default function Strategies() {
  const { data: cfg }    = useSWR<ConfigResponse>('/api/config',  fetcher, { refreshInterval: 300_000 })
  const { data: trades } = useSWR<TradesResponse>('/api/trades?source=paper', fetcher, { refreshInterval: 60_000 })

  const weights = cfg?.weights ?? {}
  const enabled = new Set(cfg?.enabled ?? [])

  // Per-strategy aggregation from trade history
  const stratMap: Record<string, { trades: number; wins: number; total_pnl: number; pnls: number[] }> = {}
  for (const t of (trades?.trades ?? [])) {
    const s = t.strategy || 'unknown'
    if (!stratMap[s]) stratMap[s] = { trades: 0, wins: 0, total_pnl: 0, pnls: [] }
    stratMap[s].trades++
    stratMap[s].total_pnl += t.pnl
    stratMap[s].pnls.push(t.pnl)
    if (t.pnl > 0) stratMap[s].wins++
  }

  const stratStats = Object.entries(stratMap)
    .map(([name, s]) => ({
      name,
      trades:    s.trades,
      wins:      s.wins,
      win_rate:  s.trades ? s.wins / s.trades * 100 : 0,
      total_pnl: s.total_pnl,
      avg_pnl:   s.trades ? s.total_pnl / s.trades : 0,
    }))
    .sort((a, b) => b.total_pnl - a.total_pnl)

  // All strategies for weight table
  const allNames = Array.from(new Set([
    ...Object.keys(weights),
    ...(cfg?.all_strategies ?? []),
  ])).sort()

  const maxW = Math.max(...Object.values(weights), 1)

  // Donut data — only strategies with weight > 0
  const donutData = Object.entries(weights)
    .filter(([, w]) => w > 0)
    .map(([name, w]) => ({ name, value: w }))
    .sort((a, b) => b.value - a.value)

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Strategies</h1>
        <span className="text-xs text-dim">
          Weights from <code className="text-blue">config/settings.yaml</code>
          {' — '}<code className="text-dim">python scripts/tune_weights.py</code> to auto-tune
        </span>
      </div>

      {/* Allocation donut + weights table */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        {/* Allocation donut */}
        {donutData.length > 0 && (
          <div className="bg-surface border border-border rounded-xl p-5 flex flex-col items-center">
            <div className="text-sm font-medium mb-4 self-start">Weight Allocation</div>
            <ResponsiveContainer width="100%" height={200}>
              <PieChart>
                <Pie
                  data={donutData}
                  cx="50%"
                  cy="50%"
                  innerRadius={55}
                  outerRadius={80}
                  paddingAngle={2}
                  dataKey="value"
                >
                  {donutData.map((_, i) => (
                    <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip
                  formatter={(v: any, name: any) => [`${Number(v).toFixed(2)}`, name]}
                  contentStyle={{ background: '#161b27', border: '1px solid #252d3d', borderRadius: 8, fontSize: 11 }}
                />
              </PieChart>
            </ResponsiveContainer>
            <div className="w-full mt-2 space-y-1">
              {donutData.slice(0, 6).map((d, i) => (
                <div key={d.name} className="flex items-center gap-2 text-xs font-mono">
                  <span
                    className="w-2.5 h-2.5 rounded-full shrink-0"
                    style={{ background: CHART_COLORS[i % CHART_COLORS.length] }}
                  />
                  <span className="text-dim truncate flex-1">{d.name}</span>
                  <span className="text-primary">{d.value.toFixed(2)}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Weights progress bars */}
        <div className={clsx(
          'bg-surface border border-border rounded-xl overflow-hidden',
          donutData.length > 0 ? 'xl:col-span-2' : 'xl:col-span-3',
        )}>
          <div className="px-5 py-3 border-b border-border text-sm font-medium">
            Strategy Weights & Status
          </div>
          <div className="overflow-y-auto max-h-96">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-dim border-b border-border">
                  {['Strategy', 'Weight', 'Bar', 'Status'].map(h => (
                    <th key={h} className="text-left px-5 py-2.5 font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {allNames.map(name => {
                  const w = weights[name] ?? 0
                  const isEnabled = enabled.has(name)
                  return (
                    <tr key={name} className="hover:bg-border/20 transition-colors">
                      <td className="px-5 py-2.5 font-mono text-sm">{name}</td>
                      <td className="px-5 py-2.5 font-mono text-sm">{w.toFixed(2)}</td>
                      <td className="px-5 py-2.5 w-40">
                        <div className="h-2 rounded-full bg-border overflow-hidden">
                          <div
                            className="h-full rounded-full bg-blue transition-all"
                            style={{ width: `${(w / maxW) * 100}%` }}
                          />
                        </div>
                      </td>
                      <td className="px-5 py-2.5">
                        <span className={clsx(
                          'inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium',
                          isEnabled ? 'bg-green/10 text-green' : 'bg-border text-dim',
                        )}>
                          <span className={clsx('w-1.5 h-1.5 rounded-full', isEnabled ? 'bg-green' : 'bg-dim')} />
                          {isEnabled ? 'Enabled' : 'Disabled'}
                        </span>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* Strategy P&L bars + per-strategy stats */}
      {stratStats.length > 0 ? (
        <>
          <div className="bg-surface border border-border rounded-xl p-5">
            <div className="text-sm font-medium mb-4">Total P&L by Strategy</div>
            <ResponsiveContainer width="100%" height={Math.max(260, stratStats.length * 32)}>
              <BarChart data={stratStats} layout="vertical" margin={{ left: 140, right: 20 }}>
                <CartesianGrid stroke="#252d3d" strokeDasharray="3 3" />
                <XAxis
                  type="number"
                  tick={{ fill: '#8892a4', fontSize: 10 }}
                  tickFormatter={v => `₹${(v / 1000).toFixed(0)}k`}
                />
                <YAxis
                  type="category"
                  dataKey="name"
                  tick={{ fill: '#e2e8f0', fontSize: 11 }}
                  width={140}
                />
                <ReferenceLine x={0} stroke="#4b5563" />
                <Tooltip
                  formatter={(v: any) => [fmt(Number(v)), 'P&L']}
                  contentStyle={{ background: '#161b27', border: '1px solid #252d3d', borderRadius: 8, fontSize: 12 }}
                />
                <Bar dataKey="total_pnl" radius={[0, 4, 4, 0]}>
                  {stratStats.map((s, i) => (
                    <Cell key={i} fill={s.total_pnl >= 0 ? '#10b981' : '#f43f5e'} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>

          <div className="bg-surface border border-border rounded-xl overflow-hidden">
            <div className="px-5 py-3 border-b border-border text-sm font-medium">Per-Strategy Performance</div>
            <table className="w-full text-xs font-mono">
              <thead>
                <tr className="text-dim border-b border-border">
                  {['Strategy', 'Trades', 'Wins', 'Win %', 'Total P&L ₹', 'Avg P&L ₹'].map(h => (
                    <th key={h} className="text-left px-5 py-2.5 font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {stratStats.map((s, i) => (
                  <tr key={i} className="hover:bg-border/20 transition-colors">
                    <td className="px-5 py-2.5 font-medium">{s.name}</td>
                    <td className="px-5 py-2.5">{s.trades}</td>
                    <td className="px-5 py-2.5 text-green">{s.wins}</td>
                    <td className={clsx('px-5 py-2.5', s.win_rate >= 50 ? 'text-green' : 'text-red')}>
                      {s.win_rate.toFixed(1)}%
                    </td>
                    <td className={clsx('px-5 py-2.5 font-semibold', s.total_pnl >= 0 ? 'text-green' : 'text-red')}>
                      {fmt(s.total_pnl)}
                    </td>
                    <td className={clsx('px-5 py-2.5', s.avg_pnl >= 0 ? 'text-green' : 'text-red')}>
                      {fmt(s.avg_pnl)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <div className="bg-surface border border-border rounded-xl p-10 text-center text-dim text-sm">
          No trade data yet — strategy performance breakdown appears after paper trading.
        </div>
      )}
    </div>
  )
}
