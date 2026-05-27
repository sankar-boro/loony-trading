import useSWR from 'swr'
import { fetcher } from '../api'
import type { EquityPoint, PositionsResponse, TradesResponse, DailyResponse } from '../types'
import {
  AreaChart, Area, BarChart, Bar, XAxis, YAxis,
  Tooltip, ResponsiveContainer, ReferenceLine, CartesianGrid,
} from 'recharts'
import clsx from 'clsx'

function KPI({ label, value, sub, up }: { label: string; value: string; sub?: string; up?: boolean }) {
  return (
    <div className="bg-surface border border-border rounded-xl p-4">
      <div className="text-xs text-dim mb-1">{label}</div>
      <div className="text-2xl font-mono font-medium">{value}</div>
      {sub && (
        <div className={clsx('text-xs mt-1 font-mono',
          up === true ? 'text-green' : up === false ? 'text-red' : 'text-dim')}>
          {sub}
        </div>
      )}
    </div>
  )
}

const fmt = (n: number) => n >= 0 ? `+₹${n.toLocaleString('en-IN', { maximumFractionDigits: 0 })}` : `-₹${Math.abs(n).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
const fmtPct = (n: number) => `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`

function CustomTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null
  return (
    <div className="bg-surface border border-border rounded-lg px-3 py-2 text-xs font-mono">
      <div className="text-dim mb-1">{label}</div>
      {payload.map((p: any) => (
        <div key={p.name} style={{ color: p.color }}>
          {p.name}: {typeof p.value === 'number' ? fmt(p.value) : p.value}
        </div>
      ))}
    </div>
  )
}

export default function Dashboard() {
  const { data: equity }    = useSWR<EquityPoint[]>('/api/equity',    fetcher, { refreshInterval: 30_000 })
  const { data: positions } = useSWR<PositionsResponse>('/api/positions', fetcher, { refreshInterval: 15_000 })
  const { data: trades }    = useSWR<TradesResponse>('/api/trades?source=paper', fetcher, { refreshInterval: 60_000 })
  const { data: daily }     = useSWR<DailyResponse>('/api/daily',     fetcher, { refreshInterval: 120_000 })

  const eqArr  = equity ?? []
  const latest = eqArr[eqArr.length - 1]
  const first  = eqArr[0]
  const capital = positions?.initial_capital ?? 500_000

  const totalReturn = latest && first
    ? (latest.equity - first.equity) / first.equity * 100
    : 0

  // Drawdown
  let peak = 0
  let maxDd = 0
  for (const p of eqArr) {
    if (p.equity > peak) peak = p.equity
    const dd = peak > 0 ? (peak - p.equity) / peak * 100 : 0
    if (dd > maxDd) maxDd = dd
  }

  const stats   = trades?.stats
  const summary = daily?.summary

  // Today P&L from positions
  const todayPnl = positions
    ? (positions.cash - positions.initial_capital) +
      (positions.positions ?? []).reduce((s, p) => s + p.unrealised_pnl, 0)
    : null

  // Equity chart data — last 200 points
  const chartData = eqArr.slice(-200).map(p => ({
    ts:       p.ts.slice(0, 16).replace('T', ' '),
    equity:   p.equity,
    drawdown: -((() => {
      let pk = 0
      for (const q of eqArr) {
        if (q.equity > pk) pk = q.equity
        if (q.ts === p.ts) return pk > 0 ? (pk - p.equity) / pk * 100 : 0
      }
      return 0
    })()),
  }))

  const eqColor = totalReturn >= 0 ? '#10b981' : '#f43f5e'

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Dashboard</h1>
        <p className="text-xs text-dim mt-0.5">
          {new Date().toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', dateStyle: 'medium', timeStyle: 'short' })} IST
        </p>
      </div>

      {/* KPI grid */}
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
        <KPI
          label="Portfolio"
          value={latest ? `₹${latest.equity.toLocaleString('en-IN', { maximumFractionDigits: 0 })}` : '—'}
          sub={fmtPct(totalReturn)}
          up={totalReturn >= 0}
        />
        <KPI
          label="Today P&L"
          value={todayPnl != null ? fmt(todayPnl) : '—'}
          up={todayPnl != null ? todayPnl >= 0 : undefined}
        />
        <KPI
          label="Max Drawdown"
          value={maxDd > 0 ? `${maxDd.toFixed(2)}%` : '—'}
          up={false}
        />
        <KPI
          label="Win Rate"
          value={stats ? `${stats.win_rate.toFixed(1)}%` : '—'}
          sub={stats ? `${stats.wins}W / ${stats.losses}L` : undefined}
          up={stats ? stats.win_rate >= 50 : undefined}
        />
        <KPI
          label="Open Positions"
          value={positions ? String(positions.positions.length) : '—'}
        />
        <KPI
          label="Total Trades"
          value={stats ? String(stats.total) : '—'}
          sub={stats ? `PF ${stats.profit_factor.toFixed(2)}` : undefined}
        />
      </div>

      {/* Equity curve */}
      {chartData.length > 1 ? (
        <div className="bg-surface border border-border rounded-xl p-5">
          <div className="text-sm font-medium mb-4">Equity Curve</div>
          <ResponsiveContainer width="100%" height={260}>
            <AreaChart data={chartData}>
              <defs>
                <linearGradient id="eqGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%"  stopColor={eqColor} stopOpacity={0.15} />
                  <stop offset="95%" stopColor={eqColor} stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="#252d3d" strokeDasharray="3 3" />
              <XAxis dataKey="ts" tick={{ fill: '#8892a4', fontSize: 10 }}
                     tickFormatter={v => v.slice(5, 16)} interval="preserveStartEnd" />
              <YAxis tick={{ fill: '#8892a4', fontSize: 10 }}
                     tickFormatter={v => `₹${(v/1000).toFixed(0)}k`} />
              <ReferenceLine y={capital} stroke="#8892a4" strokeDasharray="4 4" strokeWidth={1} />
              <Tooltip content={<CustomTooltip />} />
              <Area type="monotone" dataKey="equity" name="Equity"
                    stroke={eqColor} strokeWidth={2}
                    fill="url(#eqGrad)" dot={false} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <div className="bg-surface border border-border rounded-xl p-8 text-center text-dim text-sm">
          No equity data yet — start a paper trade session.
        </div>
      )}

      {/* Bottom row */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        {/* Open positions */}
        <div className="bg-surface border border-border rounded-xl p-5">
          <div className="text-sm font-medium mb-3">Open Positions</div>
          {positions?.positions.length ? (
            <table className="w-full text-xs font-mono">
              <thead>
                <tr className="text-dim border-b border-border">
                  {['Symbol', 'Side', 'Qty', 'Entry ₹', 'CMP ₹', 'P&L ₹', 'Strategy'].map(h => (
                    <th key={h} className="text-left pb-2 font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {positions.positions.map((p, i) => {
                  const pnlPct = p.entry_price
                    ? p.unrealised_pnl / (p.entry_price * Math.abs(p.size)) * 100
                    : 0
                  return (
                    <tr key={i} className="hover:bg-border/30 transition-colors">
                      <td className="py-2 font-medium">{p.symbol}</td>
                      <td className={p.direction === 1 ? 'text-green' : 'text-red'}>
                        {p.direction === 1 ? 'LONG' : 'SHORT'}
                      </td>
                      <td>{p.size}</td>
                      <td>{p.entry_price.toFixed(2)}</td>
                      <td>{p.current_price.toFixed(2)}</td>
                      <td className={p.unrealised_pnl >= 0 ? 'text-green' : 'text-red'}>
                        {fmt(p.unrealised_pnl)}
                        <span className="text-dim ml-1">({fmtPct(pnlPct)})</span>
                      </td>
                      <td className="text-dim">{p.strategy.slice(0, 16)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          ) : (
            <div className="text-dim text-sm">No open positions.</div>
          )}
        </div>

        {/* Daily P&L bar */}
        <div className="bg-surface border border-border rounded-xl p-5">
          <div className="text-sm font-medium mb-3">Daily P&L  (last 14 days)</div>
          {(daily?.days?.length ?? 0) > 0 ? (
            <ResponsiveContainer width="100%" height={180}>
              <BarChart data={daily!.days.slice(-14)}>
                <CartesianGrid stroke="#252d3d" strokeDasharray="3 3" />
                <XAxis dataKey="date" tick={{ fill: '#8892a4', fontSize: 10 }}
                       tickFormatter={v => v.slice(5)} />
                <YAxis tick={{ fill: '#8892a4', fontSize: 10 }}
                       tickFormatter={v => `₹${(v/1000).toFixed(0)}k`} />
                <ReferenceLine y={0} stroke="#4b5563" />
                <Tooltip content={<CustomTooltip />} />
                <Bar dataKey="realised" name="Realised"
                     fill="#10b981"
                     radius={[3, 3, 0, 0]}
                     label={false}>
                  {daily!.days.slice(-14).map((d, i) => (
                    <rect key={i} fill={d.realised >= 0 ? '#10b981' : '#f43f5e'} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="text-dim text-sm">No daily data yet.</div>
          )}
          {summary && (
            <div className="grid grid-cols-3 gap-3 mt-3 pt-3 border-t border-border text-xs font-mono">
              <div>
                <div className="text-dim">Total</div>
                <div className={summary.total_realised >= 0 ? 'text-green' : 'text-red'}>
                  {fmt(summary.total_realised)}
                </div>
              </div>
              <div>
                <div className="text-dim">Avg/day</div>
                <div className={summary.avg_daily >= 0 ? 'text-green' : 'text-red'}>
                  {fmt(summary.avg_daily)}
                </div>
              </div>
              <div>
                <div className="text-dim">Sharpe</div>
                <div>{summary.sharpe_ann.toFixed(2)}</div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
