import useSWR from 'swr'
import { fetcher } from '../api'
import type { DailyResponse } from '../types'
import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis, Tooltip,
  ResponsiveContainer, ReferenceLine, CartesianGrid, Cell,
} from 'recharts'
import clsx from 'clsx'

const inr    = (n: number) => `₹${Math.abs(n).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
const pnlFmt = (n: number) => `${n >= 0 ? '+' : '-'}${inr(n)}`
const ttStyle = { background: '#161b27', border: '1px solid #252d3d', borderRadius: 8, fontSize: 11 }

function KPI({ label, value, up }: { label: string; value: string; up?: boolean }) {
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

export default function DailyPnL() {
  const { data, isLoading } = useSWR<DailyResponse>('/api/daily', fetcher, { refreshInterval: 120_000 })

  const days    = data?.days ?? []
  const summary = data?.summary

  let cumul = 0
  const cumulData = days.map(d => { cumul += d.realised; return { date: d.date.slice(5), cum: cumul } })
  const cumulColor = cumul >= 0 ? '#10b981' : '#f43f5e'

  return (
    <div className="flex flex-col h-full p-4 gap-3 overflow-hidden">

      {/* Header */}
      <div className="flex items-center gap-3 shrink-0">
        <h1 className="text-base font-semibold tracking-wide">Daily P&L</h1>
        {isLoading && <span className="text-xs text-dim animate-pulse">Loading…</span>}
      </div>

      {/* KPIs */}
      {summary && (
        <div className="grid grid-cols-4 md:grid-cols-7 gap-2 shrink-0">
          <KPI label="Total Realised"  value={pnlFmt(summary.total_realised)}           up={summary.total_realised >= 0} />
          <KPI label="Avg Daily"       value={pnlFmt(summary.avg_daily)}                 up={summary.avg_daily >= 0} />
          <KPI label="Sharpe (ann.)"   value={summary.sharpe_ann.toFixed(2)}             up={summary.sharpe_ann >= 1} />
          <KPI label="Win Rate"        value={`${summary.overall_win_rate.toFixed(1)}%`} up={summary.overall_win_rate >= 50} />
          <KPI label="Trading Days"    value={String(days.length)} />
          <KPI label="Best Day"        value={summary.best_day ? pnlFmt(summary.best_day.realised) : '—'}   up={true} />
          <KPI label="Worst Day"       value={summary.worst_day ? pnlFmt(summary.worst_day.realised) : '—'} up={false} />
        </div>
      )}

      {days.length > 0 ? (
        <>
          {/* Charts */}
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-3 shrink-0">
            {/* Cumulative */}
            <div className="bg-surface border border-border rounded-xl p-4">
              <div className="text-xs font-medium mb-3 text-dim uppercase tracking-wide">Cumulative P&L</div>
              <ResponsiveContainer width="100%" height={150}>
                <LineChart data={cumulData} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                  <CartesianGrid stroke="#252d3d" strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="date" tick={{ fill: '#8892a4', fontSize: 9 }} tickLine={false} axisLine={false}
                         interval="preserveStartEnd" />
                  <YAxis tick={{ fill: '#8892a4', fontSize: 9 }} tickLine={false} axisLine={false}
                         width={50} tickFormatter={v => `${(v / 1000).toFixed(0)}k`} />
                  <ReferenceLine y={0} stroke="#4b5563" strokeDasharray="4 2" />
                  <Tooltip formatter={(v: any) => [pnlFmt(Number(v)), 'Cumulative']} contentStyle={ttStyle} />
                  <Line type="monotone" dataKey="cum" stroke={cumulColor} strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>

            {/* Daily bars */}
            <div className="bg-surface border border-border rounded-xl p-4">
              <div className="text-xs font-medium mb-3 text-dim uppercase tracking-wide">Daily Realised</div>
              <ResponsiveContainer width="100%" height={150}>
                <BarChart data={days} barCategoryGap="20%" margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                  <CartesianGrid stroke="#252d3d" strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="date" tick={{ fill: '#8892a4', fontSize: 9 }} tickLine={false} axisLine={false}
                         tickFormatter={v => v.slice(5)} interval="preserveStartEnd" />
                  <YAxis tick={{ fill: '#8892a4', fontSize: 9 }} tickLine={false} axisLine={false}
                         width={50} tickFormatter={v => `${(v / 1000).toFixed(0)}k`} />
                  <ReferenceLine y={0} stroke="#4b5563" />
                  <Tooltip formatter={(v: any) => [pnlFmt(Number(v)), 'Realised']} contentStyle={ttStyle} />
                  <Bar dataKey="realised" radius={[2, 2, 0, 0]} maxBarSize={20}>
                    {days.map((d, i) => (
                      <Cell key={i} fill={d.realised >= 0 ? '#10b981' : '#f43f5e'} fillOpacity={0.85} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Table */}
          <div className="flex-1 bg-surface border border-border rounded-xl flex flex-col min-h-0 overflow-hidden">
            <div className="px-4 py-3 border-b border-border shrink-0">
              <span className="text-sm font-medium">Day-by-Day</span>
            </div>
            <div className="flex-1 overflow-auto min-h-0">
              <table className="w-full text-xs font-mono min-w-[560px]">
                <thead className="sticky top-0 bg-surface z-10">
                  <tr className="border-b border-border">
                    {['Date', 'Realised ₹', 'Trades', 'W / L', 'Win %', 'Max DD %', 'Top Symbol'].map(h => (
                      <th key={h} className="text-left px-4 py-2.5 text-[9px] uppercase tracking-wide text-dim font-medium whitespace-nowrap">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/50">
                  {[...days].reverse().map((d, i) => (
                    <tr key={i} className="hover:bg-white/3 transition-colors">
                      <td className="px-4 py-2.5 font-medium">{d.date}</td>
                      <td className={clsx('px-4 py-2.5 font-semibold', d.realised >= 0 ? 'text-green' : 'text-red')}>
                        {pnlFmt(d.realised)}
                      </td>
                      <td className="px-4 py-2.5 text-dim">{d.trades}</td>
                      <td className="px-4 py-2.5">
                        <span className="text-green">{d.wins}</span>
                        <span className="text-dim"> / </span>
                        <span className="text-red">{d.losses}</span>
                      </td>
                      <td className={clsx('px-4 py-2.5', d.win_rate >= 50 ? 'text-green' : 'text-red')}>
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
        <div className="flex-1 bg-surface border border-border rounded-xl flex flex-col items-center justify-center gap-2 text-dim">
          <span className="text-3xl opacity-20">▤</span>
          <span className="text-sm">No daily data yet</span>
          <code className="text-xs text-blue mt-1">python scripts/paper_trade.py</code>
        </div>
      )}
    </div>
  )
}
