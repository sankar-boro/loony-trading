import { useState, useEffect } from 'react'
import useSWR from 'swr'
import { fetcher } from '../api'
import type {
  EquityPoint, PositionsResponse, TradesResponse, DailyResponse,
  WatchlistResponse, MarketResponse, SignalItem,
} from '../types'
import {
  AreaChart, Area, BarChart, Bar, XAxis, YAxis,
  Tooltip, ResponsiveContainer, ReferenceLine, CartesianGrid, Cell,
} from 'recharts'
import clsx from 'clsx'

// ── Format helpers ─────────────────────────────────────────────────────────────

const fmt = (n: number) =>
  n >= 0
    ? `+₹${n.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
    : `-₹${Math.abs(n).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`

const fmtPct = (n: number) => `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`

const fmtPrice = (n: number) =>
  n.toLocaleString('en-IN', { maximumFractionDigits: 2 })

// ── KPI Card ───────────────────────────────────────────────────────────────────

function KPI({
  label, value, sub, up,
}: {
  label: string
  value: string
  sub?: string
  up?: boolean
}) {
  return (
    <div className="bg-surface border border-border rounded-xl p-4">
      <div className="text-xs text-dim mb-1">{label}</div>
      <div className="text-2xl font-mono font-medium truncate">{value}</div>
      {sub && (
        <div
          className={clsx(
            'text-xs mt-1 font-mono',
            up === true ? 'text-green' : up === false ? 'text-red' : 'text-dim',
          )}>
          {sub}
        </div>
      )}
    </div>
  )
}

// ── Tooltip ────────────────────────────────────────────────────────────────────

function EqTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null
  return (
    <div className="bg-surface border border-border rounded-lg px-3 py-2 text-xs font-mono shadow-lg">
      <div className="text-dim mb-1">{label}</div>
      {payload.map((p: any) => (
        <div key={p.name} style={{ color: p.color }}>
          {p.name}: ₹{Number(p.value).toLocaleString('en-IN', { maximumFractionDigits: 0 })}
        </div>
      ))}
    </div>
  )
}

function PnlTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null
  const v = payload[0]?.value ?? 0
  return (
    <div className="bg-surface border border-border rounded-lg px-3 py-2 text-xs font-mono shadow-lg">
      <div className="text-dim mb-1">{label}</div>
      <div className={v >= 0 ? 'text-green' : 'text-red'}>{fmt(v)}</div>
    </div>
  )
}

// ── SSE live-price hook ────────────────────────────────────────────────────────
// Single EventSource shared between MarketBar and WatchlistPanel via state
// lifted into Dashboard. Both components receive props instead of fetching.

interface PriceSnap {
  watchlist: WatchlistResponse
  market: MarketResponse
  ts: number
}

function useLivePrices(): { snap: PriceSnap | null; live: boolean } {
  const [snap, setSnap] = useState<PriceSnap | null>(null)
  const [live, setLive]  = useState(false)

  useEffect(() => {
    const es = new EventSource('/api/stream/prices')
    es.onopen    = () => setLive(true)
    es.onerror   = () => setLive(false)
    es.onmessage = (e) => {
      try {
        const d = JSON.parse(e.data)
        if (d && d.watchlist) setSnap(d as PriceSnap)
      } catch { /* ignore malformed frames */ }
    }
    return () => es.close()
  }, [])

  return { snap, live }
}

// ── Market Bar ─────────────────────────────────────────────────────────────────

function MarketBar({ market, live }: { market: MarketResponse | null; live: boolean }) {
  if (!market || Object.keys(market).length === 0) {
    return (
      <div className="bg-surface border border-border rounded-xl px-4 py-2.5 flex items-center gap-6 text-xs font-mono text-dim">
        <span className="animate-pulse">Fetching index data…</span>
      </div>
    )
  }

  const order = ['NIFTY50', 'BANKNIFTY', 'NIFTYIT']
  return (
    <div className="bg-surface border border-border rounded-xl px-4 py-2.5 flex items-center gap-6 text-xs font-mono overflow-x-auto">
      {order.map(sym => {
        const d = market[sym]
        if (!d) return null
        const up = d.change_pct >= 0
        return (
          <div key={sym} className="flex items-center gap-2 whitespace-nowrap">
            <span className="text-dim">{sym}</span>
            <span className="text-primary font-medium">{fmtPrice(d.ltp)}</span>
            <span className={up ? 'text-green' : 'text-red'}>
              {fmtPct(d.change_pct)}
            </span>
          </div>
        )
      })}
      <span className={clsx('ml-auto text-xs', live ? 'text-green' : 'text-dim')}>
        {live ? '● live' : '○ connecting'}
      </span>
    </div>
  )
}

// ── Watchlist Panel ────────────────────────────────────────────────────────────

function WatchlistPanel({ watchlist }: { watchlist: WatchlistResponse | null }) {
  const items = watchlist ? Object.entries(watchlist) : []

  return (
    <div className="bg-surface border border-border rounded-xl flex flex-col h-full">
      <div className="px-4 py-3 border-b border-border text-sm font-medium flex items-center justify-between">
        <span>Watchlist</span>
        <span className="text-xs text-dim">SSE stream</span>
      </div>
      <div className="flex-1 overflow-y-auto divide-y divide-border">
        {items.length === 0 ? (
          <div className="px-4 py-6 text-xs text-dim text-center">Loading…</div>
        ) : (
          items.map(([sym, d]) => {
            const up = d.change_pct >= 0
            return (
              <div key={sym} className="px-4 py-2.5 flex items-center justify-between hover:bg-border/20 transition-colors">
                <div className="text-sm font-medium font-mono">{sym}</div>
                <div className="text-right">
                  <div className="text-sm font-mono font-medium">
                    {d.ltp > 0 ? `₹${fmtPrice(d.ltp)}` : '—'}
                  </div>
                  <div className={clsx('text-xs font-mono', up ? 'text-green' : 'text-red')}>
                    {fmtPct(d.change_pct)}
                  </div>
                </div>
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}

// ── Signals Feed ───────────────────────────────────────────────────────────────

function SignalsFeed() {
  const { data } = useSWR<SignalItem[]>('/api/signals', fetcher, {
    refreshInterval: 60_000,
  })

  const signals = data ?? []

  return (
    <div className="bg-surface border border-border rounded-xl flex flex-col h-full">
      <div className="px-4 py-3 border-b border-border text-sm font-medium flex items-center justify-between">
        <span>Live Signals</span>
        <span className="text-xs text-dim">{signals.length} active</span>
      </div>
      <div className="flex-1 overflow-y-auto divide-y divide-border">
        {signals.length === 0 ? (
          <div className="px-4 py-6 text-xs text-dim text-center">
            No signals — market may be closed.
          </div>
        ) : (
          signals.slice(0, 10).map((s, i) => {
            const isBuy = s.signal === 'BUY'
            return (
              <div key={i} className="px-4 py-2.5 hover:bg-border/20 transition-colors">
                <div className="flex items-center gap-2 mb-1">
                  <span
                    className={clsx(
                      'text-xs font-semibold px-1.5 py-0.5 rounded',
                      isBuy ? 'bg-green/10 text-green' : 'bg-red/10 text-red',
                    )}>
                    {s.signal}
                  </span>
                  <span className="text-sm font-mono font-medium">{s.symbol}</span>
                  <span className="ml-auto text-xs text-dim">{s.ts.slice(11, 19)}</span>
                </div>
                <div className="text-xs text-dim mb-1.5">{s.strategy}</div>
                <div className="flex items-center gap-2">
                  <span className="text-xs font-mono text-primary">
                    ₹{fmtPrice(s.price)}
                  </span>
                  <div className="flex-1 h-1.5 rounded-full bg-border overflow-hidden">
                    <div
                      className={clsx('h-full rounded-full', isBuy ? 'bg-green' : 'bg-red')}
                      style={{ width: `${Math.min(100, s.confidence * 100)}%` }}
                    />
                  </div>
                  <span className="text-xs text-dim">{(s.confidence * 100).toFixed(0)}%</span>
                </div>
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}

// ── Main Dashboard ─────────────────────────────────────────────────────────────

export default function Dashboard() {
  const { data: equity }    = useSWR<EquityPoint[]>('/api/equity', fetcher, { refreshInterval: 30_000 })
  const { data: positions } = useSWR<PositionsResponse>('/api/positions', fetcher, { refreshInterval: 15_000 })
  const { data: trades }    = useSWR<TradesResponse>('/api/trades?source=paper', fetcher, { refreshInterval: 60_000 })
  const { data: daily }     = useSWR<DailyResponse>('/api/daily', fetcher, { refreshInterval: 120_000 })
  const { snap: priceSnap, live: priceLive } = useLivePrices()

  const eqArr  = equity ?? []
  const latest = eqArr[eqArr.length - 1]
  const capital = positions?.initial_capital ?? 500_000

  const totalReturn = latest ? (latest.equity - capital) / capital * 100 : 0

  const stats   = trades?.stats
  const summary = daily?.summary

  // Today P&L
  const todayPnl = positions
    ? (positions.cash - positions.initial_capital) +
      (positions.positions ?? []).reduce((s, p) => s + p.unrealised_pnl, 0)
    : null

  // Equity chart data — last 180 points, sample every N if too many
  const eqSample = eqArr.length > 200 ? eqArr.filter((_, i) => i % Math.ceil(eqArr.length / 200) === 0) : eqArr
  const chartData = eqSample.map(p => ({
    ts:     p.ts.slice(0, 10),
    equity: p.equity,
  }))

  const eqColor = totalReturn >= 0 ? '#10b981' : '#f43f5e'

  // Daily P&L bar chart — last 30 days
  const last30 = (daily?.days ?? []).slice(-30)

  return (
    <div className="p-6 space-y-4">
      {/* Market bar */}
      <MarketBar market={priceSnap?.market ?? null} live={priceLive} />

      {/* KPI cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
        <KPI
          label="Portfolio Value"
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
          label="Total Return"
          value={fmtPct(totalReturn)}
          sub={latest ? `₹${latest.equity.toLocaleString('en-IN', { maximumFractionDigits: 0 })}` : undefined}
          up={totalReturn >= 0}
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
          sub={positions ? `${positions.positions.length} active` : undefined}
        />
        <KPI
          label="Sharpe (ann.)"
          value={summary ? summary.sharpe_ann.toFixed(2) : '—'}
          sub={summary ? `${summary.total_trades} trades` : undefined}
          up={summary ? summary.sharpe_ann >= 1 : undefined}
        />
      </div>

      {/* Middle row: Equity curve (2/3) + Watchlist (1/3) */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4" style={{ minHeight: 320 }}>
        {/* Equity curve */}
        <div className="xl:col-span-2 bg-surface border border-border rounded-xl p-5">
          <div className="text-sm font-medium mb-4 flex items-center justify-between">
            <span>Equity Curve</span>
            <span className={clsx('text-xs font-mono', totalReturn >= 0 ? 'text-green' : 'text-red')}>
              {fmtPct(totalReturn)}
            </span>
          </div>
          {chartData.length > 1 ? (
            <ResponsiveContainer width="100%" height={260}>
              <AreaChart data={chartData}>
                <defs>
                  <linearGradient id="eqGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%"  stopColor={eqColor} stopOpacity={0.18} />
                    <stop offset="95%" stopColor={eqColor} stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="#252d3d" strokeDasharray="3 3" />
                <XAxis
                  dataKey="ts"
                  tick={{ fill: '#8892a4', fontSize: 10 }}
                  tickFormatter={v => v.slice(5)}
                  interval="preserveStartEnd"
                />
                <YAxis
                  tick={{ fill: '#8892a4', fontSize: 10 }}
                  tickFormatter={v => `₹${(v / 1000).toFixed(0)}k`}
                  width={55}
                />
                <ReferenceLine y={capital} stroke="#8892a4" strokeDasharray="4 4" strokeWidth={1} label={{ value: 'Capital', fill: '#8892a4', fontSize: 9 }} />
                <Tooltip content={<EqTooltip />} />
                <Area
                  type="monotone"
                  dataKey="equity"
                  name="Equity"
                  stroke={eqColor}
                  strokeWidth={2}
                  fill="url(#eqGrad)"
                  dot={false}
                />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex items-center justify-center h-64 text-dim text-sm">
              No equity data yet — run the seed script first.
            </div>
          )}
        </div>

        {/* Watchlist */}
        <div className="xl:col-span-1" style={{ minHeight: 320 }}>
          <WatchlistPanel watchlist={priceSnap?.watchlist ?? null} />
        </div>
      </div>

      {/* Lower row: Open Positions (1/2) + Signals (1/2) */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4" style={{ minHeight: 260 }}>
        {/* Open positions */}
        <div className="bg-surface border border-border rounded-xl overflow-hidden">
          <div className="px-5 py-3 border-b border-border text-sm font-medium flex items-center justify-between">
            <span>Open Positions ({positions?.positions.length ?? 0})</span>
            {(positions?.positions.length ?? 0) > 0 && (
              <span className={clsx(
                'text-sm font-mono',
                (positions!.positions.reduce((s, p) => s + p.unrealised_pnl, 0)) >= 0
                  ? 'text-green' : 'text-red',
              )}>
                {fmt(positions!.positions.reduce((s, p) => s + p.unrealised_pnl, 0))} unrealised
              </span>
            )}
          </div>
          {(positions?.positions.length ?? 0) > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-xs font-mono">
                <thead>
                  <tr className="text-dim border-b border-border">
                    {['Symbol', 'Side', 'Qty', 'Entry ₹', 'CMP ₹', 'P&L ₹', 'Strategy'].map(h => (
                      <th key={h} className="text-left px-4 py-2.5 font-medium whitespace-nowrap">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {positions!.positions.map((p, i) => {
                    const pnlPct = p.entry_price
                      ? p.unrealised_pnl / (p.entry_price * Math.abs(p.size)) * 100 : 0
                    return (
                      <tr key={i} className="hover:bg-border/20 transition-colors">
                        <td className="px-4 py-2.5 font-semibold">{p.symbol}</td>
                        <td className={clsx('px-4 py-2.5 font-semibold',
                          p.direction === 1 ? 'text-green' : 'text-red')}>
                          {p.direction === 1 ? '▲ LONG' : '▼ SHORT'}
                        </td>
                        <td className="px-4 py-2.5">{Math.round(p.size)}</td>
                        <td className="px-4 py-2.5">{p.entry_price.toFixed(2)}</td>
                        <td className="px-4 py-2.5">{p.current_price.toFixed(2)}</td>
                        <td className={clsx('px-4 py-2.5 font-semibold',
                          p.unrealised_pnl >= 0 ? 'text-green' : 'text-red')}>
                          {fmt(p.unrealised_pnl)}
                          <span className="text-dim ml-1">({fmtPct(pnlPct)})</span>
                        </td>
                        <td className="px-4 py-2.5 text-dim">{p.strategy.slice(0, 18)}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="px-5 py-8 text-center text-dim text-sm">
              {positions ? 'No open positions.' : 'No position data — bot not running.'}
            </div>
          )}
        </div>

        {/* Signals */}
        <SignalsFeed />
      </div>

      {/* Daily P&L bar chart — last 30 days */}
      {last30.length > 0 ? (
        <div className="bg-surface border border-border rounded-xl p-5">
          <div className="text-sm font-medium mb-4 flex items-center justify-between">
            <span>Daily P&L — Last 30 Days</span>
            {summary && (
              <span className={clsx('text-xs font-mono', summary.total_realised >= 0 ? 'text-green' : 'text-red')}>
                Total {fmt(summary.total_realised)}
              </span>
            )}
          </div>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={last30} barCategoryGap="20%">
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
              <Tooltip content={<PnlTooltip />} />
              <Bar dataKey="realised" name="Realised P&L" radius={[3, 3, 0, 0]}>
                {last30.map((d, i) => (
                  <Cell key={i} fill={d.realised >= 0 ? '#10b981' : '#f43f5e'} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <div className="bg-surface border border-border rounded-xl p-8 text-center text-dim text-sm">
          No daily P&L data yet — run <code className="text-blue">python scripts/seed_dashboard_data.py</code>
        </div>
      )}
    </div>
  )
}
