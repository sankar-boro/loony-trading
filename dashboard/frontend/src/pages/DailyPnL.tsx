import useSWR from 'swr'
import { fetcher } from '../api'
import type { DailyResponse } from '../types'
import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  ReferenceLine, CartesianGrid, Cell,
} from 'recharts'
import clsx from 'clsx'

const fmt = (n: number) =>
  `${n >= 0 ? '+' : '-'}₹${Math.abs(n).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`

export default function DailyPnL() {
  const { data, isLoading } = useSWR<DailyResponse>('/api/daily', fetcher, { refreshInterval: 120_000 })

  const days    = data?.days ?? []
  const summary = data?.summary

  // ── Cumulative P&L line chart ──────────────────────────────────────────────

  let cumulative = 0
  const cumulData = days.map(d => {
    cumulative += d.realised
    return { date: d.date.slice(5), cumPnl: cumulative }
  })

  return (
    <div className="p-6 space-y-5">
      <div className="flex items-center gap-3">
        <h1 className="text-xl font-semibold">Daily P&L</h1>
        {isLoading && <span className="text-xs text-dim animate-pulse">Loading…</span>}
      </div>

      {/* Summary KPIs */}
      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-7 gap-3">
          {[
            { label: 'Total Realised', value: fmt(summary.total_realised),                up: summary.total_realised >= 0 },
            { label: 'Avg Daily',      value: fmt(summary.avg_daily),                     up: summary.avg_daily >= 0 },
            { label: 'Sharpe (ann.)',  value: summary.sharpe_ann.toFixed(2),              up: summary.sharpe_ann >= 1 },
            { label: 'Win Rate',       value: `${summary.overall_win_rate.toFixed(1)}%`,  up: summary.overall_win_rate >= 50 },
            { label: 'Trading Days',   value: String(days.length),                        up: undefined },
            { label: 'Best Day',       value: summary.best_day ? fmt(summary.best_day.realised) : '—', up: true },
            { label: 'Worst Day',      value: summary.worst_day ? fmt(summary.worst_day.realised) : '—', up: false },
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

      {days.length > 0 ? (
        <>
          {/* Cumulative P&L line chart */}
          <div className="bg-surface border border-border rounded-xl p-5">
            <div className="text-sm font-medium mb-4">Cumulative P&L</div>
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={cumulData}>
                <CartesianGrid stroke="#252d3d" strokeDasharray="3 3" />
                <XAxis
                  dataKey="date"
                  tick={{ fill: '#8892a4', fontSize: 10 }}
                  interval="preserveStartEnd"
                />
                <YAxis
                  tick={{ fill: '#8892a4', fontSize: 10 }}
                  tickFormatter={v => `₹${(v / 1000).toFixed(0)}k`}
                  width={55}
                />
                <ReferenceLine y={0} stroke="#4b5563" />
                <Tooltip
                  formatter={(v: any) => [fmt(Number(v)), 'Cumulative P&L']}
                  contentStyle={{ background: '#161b27', border: '1px solid #252d3d', borderRadius: 8, fontSize: 12 }}
                />
                <Line
                  type="monotone"
                  dataKey="cumPnl"
                  stroke={cumulData.length ? (cumulData[cumulData.length - 1].cumPnl >= 0 ? '#10b981' : '#f43f5e') : '#3b82f6'}
                  strokeWidth={2}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>

          {/* Daily bar chart */}
          <div className="bg-surface border border-border rounded-xl p-5">
            <div className="text-sm font-medium mb-4">Daily Realised P&L</div>
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={days} barCategoryGap="30%">
                <CartesianGrid stroke="#252d3d" strokeDasharray="3 3" />
                <XAxis
                  dataKey="date"
                  tick={{ fill: '#8892a4', fontSize: 10 }}
                  tickFormatter={v => v.slice(5)}
                  interval="preserveStartEnd"
                />
                <YAxis
                  tick={{ fill: '#8892a4', fontSize: 10 }}
                  tickFormatter={v => `₹${(v / 1000).toFixed(0)}k`}
                  width={55}
                />
                <ReferenceLine y={0} stroke="#4b5563" />
                <Tooltip
                  formatter={(v: any) => [fmt(Number(v)), 'Realised']}
                  contentStyle={{ background: '#161b27', border: '1px solid #252d3d', borderRadius: 8, fontSize: 12 }}
                />
                <Bar dataKey="realised" radius={[4, 4, 0, 0]}>
                  {days.map((d, i) => (
                    <Cell key={i} fill={d.realised >= 0 ? '#10b981' : '#f43f5e'} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>

          {/* Table */}
          <div className="bg-surface border border-border rounded-xl overflow-hidden">
            <div className="px-5 py-3 border-b border-border text-sm font-medium">Day-by-Day</div>
            <div className="overflow-x-auto">
              <table className="w-full text-xs font-mono">
                <thead>
                  <tr className="text-dim border-b border-border">
                    {['Date', 'Realised ₹', 'Trades', 'Wins', 'Losses', 'Win %', 'Max DD %', 'Top Symbol'].map(h => (
                      <th key={h} className="text-left px-4 py-2.5 font-medium whitespace-nowrap">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {[...days].reverse().map((d, i) => (
                    <tr key={i} className="hover:bg-border/20 transition-colors">
                      <td className="px-4 py-2.5 font-medium">{d.date}</td>
                      <td className={clsx('px-4 py-2.5 font-semibold',
                        d.realised >= 0 ? 'text-green' : 'text-red')}>
                        {fmt(d.realised)}
                      </td>
                      <td className="px-4 py-2.5">{d.trades}</td>
                      <td className="px-4 py-2.5 text-green">{d.wins}</td>
                      <td className="px-4 py-2.5 text-red">{d.losses}</td>
                      <td className={clsx('px-4 py-2.5',
                        d.win_rate >= 50 ? 'text-green' : 'text-red')}>
                        {d.win_rate.toFixed(1)}%
                      </td>
                      <td className="px-4 py-2.5 text-amber">{d.max_drawdown_pct.toFixed(2)}%</td>
                      <td className="px-4 py-2.5 text-dim">{d.top_symbol || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      ) : (
        <div className="bg-surface border border-border rounded-xl p-10 text-center text-dim text-sm">
          No daily data yet — runs after first trading session or after seeding.
        </div>
      )}
    </div>
  )
}
