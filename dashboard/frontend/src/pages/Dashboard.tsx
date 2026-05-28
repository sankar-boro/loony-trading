import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import useSWR from 'swr'
import { fetcher } from '../api'
import type {
  EquityPoint, PositionsResponse, TradesResponse,
  WatchlistResponse, MarketResponse, SignalItem, UniverseResponse,
} from '../types'
import {
  AreaChart, Area, XAxis, YAxis,
  Tooltip, ResponsiveContainer, ReferenceLine, CartesianGrid,
} from 'recharts'
import clsx from 'clsx'

// ── Shared helpers ─────────────────────────────────────────────────────────────

const inr   = (n: number) => `₹${Math.abs(n).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
const pnl   = (n: number) => `${n >= 0 ? '+' : '-'}${inr(n)}`
const pct   = (n: number) => `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`
const price = (n: number) => n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

// ── Panel chrome ──────────────────────────────────────────────────────────────

function Panel({ title, right, children, className = '' }: {
  title: React.ReactNode
  right?: React.ReactNode
  children: React.ReactNode
  className?: string
}) {
  return (
    <div className={clsx('bg-surface border border-border rounded-xl flex flex-col min-h-0 overflow-hidden', className)}>
      <div className="flex items-center justify-between px-4 py-3 border-b border-border shrink-0">
        <span className="text-sm font-medium text-primary">{title}</span>
        {right && <span className="text-xs text-dim">{right}</span>}
      </div>
      {children}
    </div>
  )
}

// ── KPI card ──────────────────────────────────────────────────────────────────

function KPI({ label, value, sub, up }: {
  label: string; value: string; sub?: string; up?: boolean
}) {
  return (
    <div className="bg-surface border border-border rounded-xl px-4 py-3">
      <div className="text-xs text-dim mb-1 uppercase tracking-wide">{label}</div>
      <div className={clsx('text-lg font-mono font-semibold truncate',
        up === true ? 'text-green' : up === false ? 'text-red' : 'text-primary')}>
        {value}
      </div>
      {sub && (
        <div className={clsx('text-xs font-mono mt-0.5',
          up === true ? 'text-green/70' : up === false ? 'text-red/70' : 'text-dim')}>
          {sub}
        </div>
      )}
    </div>
  )
}

// ── SSE live-price hook ────────────────────────────────────────────────────────

interface PriceSnap { watchlist: WatchlistResponse; market: MarketResponse; ts: number }

function useLivePrices() {
  const [snap, setSnap] = useState<PriceSnap | null>(null)
  const [live, setLive] = useState(false)
  useEffect(() => {
    const es = new EventSource('/api/stream/prices')
    es.onopen    = () => setLive(true)
    es.onerror   = () => setLive(false)
    es.onmessage = (e) => { try { const d = JSON.parse(e.data); if (d?.watchlist) setSnap(d) } catch {} }
    return () => es.close()
  }, [])
  return { snap, live }
}

// ── Market Ticker ─────────────────────────────────────────────────────────────

function MarketTicker({ market, live }: { market: MarketResponse | null; live: boolean }) {
  const indices = ['NIFTY50', 'BANKNIFTY', 'NIFTYIT']
  return (
    <div className="h-10 bg-surface border border-border rounded-xl px-4 flex items-center gap-6 text-xs font-mono shrink-0 overflow-x-auto">
      {indices.map(sym => {
        const d = market?.[sym]
        const up = (d?.change_pct ?? 0) >= 0
        return (
          <div key={sym} className="flex items-center gap-2 whitespace-nowrap">
            <span className="text-dim">{sym}</span>
            {d && d.ltp > 0 ? (
              <>
                <span className="text-primary font-medium">{price(d.ltp)}</span>
                <span className={up ? 'text-green' : 'text-red'}>{pct(d.change_pct)}</span>
              </>
            ) : (
              <span className="text-dim">—</span>
            )}
          </div>
        )
      })}
      <div className="ml-auto flex items-center gap-1.5 shrink-0">
        <span className={clsx('w-1.5 h-1.5 rounded-full', live ? 'bg-green animate-pulse' : 'bg-muted')} />
        <span className="text-dim">{live ? 'live' : 'connecting'}</span>
      </div>
    </div>
  )
}

// ── Watchlist Panel ───────────────────────────────────────────────────────────

function WatchlistPanel({ watchlist }: { watchlist: WatchlistResponse | null }) {
  const navigate = useNavigate()
  const { data: universe } = useSWR<UniverseResponse>('/api/universe', fetcher, {
    revalidateOnFocus: false, revalidateOnReconnect: false,
  })
  const [activeTab, setActiveTab] = useState('Watchlist')
  const [search,    setSearch]    = useState('')
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())

  const tabs = ['Watchlist', ...(universe?.sectors.map(s => s.sector) ?? [])]

  const toggle = (s: string) => setCollapsed(p => {
    const n = new Set(p); n.has(s) ? n.delete(s) : n.add(s); return n
  })

  const displaySectors = (() => {
    if (!universe) return []
    if (activeTab === 'Watchlist') {
      const wl = new Set(universe.watchlist)
      const grouped: Record<string, typeof universe.sectors[0]['stocks']> = {}
      universe.sectors.forEach(sec => {
        const stocks = sec.stocks.filter(st => wl.has(st.symbol))
        if (stocks.length) grouped[sec.sector] = stocks
      })
      return Object.entries(grouped).map(([sector, stocks]) => ({
        sector, color: universe.sectors.find(s => s.sector === sector)?.color ?? '#64748b', stocks,
      }))
    }
    return universe.sectors.filter(s => s.sector === activeTab)
  })()

  const q = search.toLowerCase()
  const filtered = displaySectors.map(sec => ({
    ...sec,
    stocks: q
      ? sec.stocks.filter(st => st.symbol.toLowerCase().includes(q) || st.name.toLowerCase().includes(q))
      : sec.stocks,
  })).filter(sec => sec.stocks.length > 0)

  return (
    <Panel title="Universe" right={universe ? `${universe.total_stocks} stocks` : undefined} className="h-full">
      {/* Search */}
      <div className="px-3 py-2 border-b border-border shrink-0">
        <input
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Symbol or company…"
          className="w-full text-xs bg-bg border border-border rounded px-2.5 py-1.5 focus:outline-none focus:border-blue placeholder:text-dim"
        />
      </div>

      {/* Sector tabs */}
      <div className="flex overflow-x-auto border-b border-border shrink-0 scrollbar-thin">
        {tabs.map(tab => {
          const sec = universe?.sectors.find(s => s.sector === tab)
          return (
            <button
              key={tab}
              onClick={() => { setActiveTab(tab); setSearch('') }}
              className={clsx(
                'px-3 py-2 text-xs whitespace-nowrap shrink-0 border-b-2 transition-colors',
                activeTab === tab
                  ? 'border-blue text-primary font-medium'
                  : 'border-transparent text-dim hover:text-primary',
              )}
            >
              {tab === 'Watchlist' ? '⭐' : ''} {tab}
              {sec && <span className="ml-1 text-[9px] text-dim">({sec.stocks.length})</span>}
            </button>
          )
        })}
      </div>

      {/* Stock rows */}
      <div className="flex-1 overflow-y-auto min-h-0">
        {filtered.length === 0 ? (
          <div className="flex items-center justify-center h-24 text-xs text-dim">
            {universe ? 'No matches' : 'Loading…'}
          </div>
        ) : (
          filtered.map(sec => (
            <div key={sec.sector}>
              {filtered.length > 1 && (
                <button
                  onClick={() => toggle(sec.sector)}
                  className="w-full flex items-center gap-2 px-3 py-1.5 bg-bg/40 hover:bg-bg/60 transition-colors"
                >
                  <span className="w-2 h-2 rounded-full shrink-0" style={{ background: sec.color }} />
                  <span className="text-[10px] font-medium text-dim uppercase tracking-wide">{sec.sector}</span>
                  <span className="text-[9px] text-dim ml-1">({sec.stocks.length})</span>
                  <span className="ml-auto text-[10px] text-dim">{collapsed.has(sec.sector) ? '▶' : '▼'}</span>
                </button>
              )}
              {!collapsed.has(sec.sector) && sec.stocks.map(st => {
                const p = watchlist?.[st.symbol]
                const up = (p?.change_pct ?? 0) >= 0
                return (
                  <button
                    key={st.symbol}
                    onClick={() => navigate('/chart', { state: { symbol: st.symbol } })}
                    className="w-full flex items-center px-3 py-2 hover:bg-blue/5 border-b border-border/30 last:border-0 transition-colors text-left group cursor-pointer"
                  >
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1">
                        <span className="text-xs font-mono font-semibold group-hover:text-blue transition-colors">{st.symbol}</span>
                        {st.fno    && <span className="text-[8px] px-1 rounded bg-blue/10 text-blue leading-tight">F&O</span>}
                        {st.nifty50 && <span className="text-[8px] px-1 rounded bg-amber/10 text-amber leading-tight">N50</span>}
                      </div>
                      <div className="text-[10px] text-dim truncate">{st.name}</div>
                    </div>
                    <div className="text-right ml-2 shrink-0">
                      {p && p.ltp > 0 ? (
                        <>
                          <div className="text-xs font-mono">₹{price(p.ltp)}</div>
                          <div className={clsx('text-[10px] font-mono', up ? 'text-green' : 'text-red')}>
                            {pct(p.change_pct)}
                          </div>
                        </>
                      ) : (
                        <span className="text-xs text-dim">—</span>
                      )}
                    </div>
                  </button>
                )
              })}
            </div>
          ))
        )}
      </div>
    </Panel>
  )
}

// ── Signals feed ──────────────────────────────────────────────────────────────

function SignalsFeed() {
  const { data } = useSWR<SignalItem[]>('/api/signals', fetcher, { refreshInterval: 60_000 })
  const signals = data ?? []

  return (
    <Panel title="Live Signals" right={`${signals.length} active`} className="h-full">
      <div className="flex-1 divide-y divide-border overflow-y-auto min-h-0">
        {signals.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full gap-2 text-dim">
            <span className="text-2xl opacity-20">◎</span>
            <span className="text-xs text-center px-4">No signals above threshold</span>
            <span className="text-[10px] text-dim">Scan runs every 60s</span>
          </div>
        ) : (
          signals.map((s, i) => {
            const isBuy = s.signal === 'BUY'
            const confPct = (s.confidence * 100).toFixed(0)
            return (
              <div key={i} className="px-4 py-3 hover:bg-white/3 transition-colors">
                {/* Row 1: badge + symbol + price */}
                <div className="flex items-center gap-2.5 mb-1.5">
                  <span className={clsx(
                    'text-[10px] font-bold px-2 py-0.5 rounded shrink-0',
                    isBuy ? 'bg-green/15 text-green' : 'bg-red/15 text-red',
                  )}>{s.signal}</span>
                  <span className="text-sm font-mono font-bold flex-1">{s.symbol}</span>
                  <span className="text-sm font-mono font-medium">₹{price(s.price)}</span>
                </div>
                {/* Row 2: strategy + confidence bar */}
                <div className="flex items-center gap-2">
                  <span className="text-[10px] text-dim truncate flex-1">{s.strategy}</span>
                  <div className="flex items-center gap-1.5 shrink-0">
                    <div className="w-16 h-1.5 rounded-full bg-border overflow-hidden">
                      <div
                        className={clsx('h-full rounded-full', isBuy ? 'bg-green' : 'bg-red')}
                        style={{ width: `${s.confidence * 100}%`, opacity: 0.7 }}
                      />
                    </div>
                    <span className="text-[10px] font-mono text-dim w-8 text-right">{confPct}%</span>
                  </div>
                </div>
                {/* Row 3: SL / TP */}
                <div className="flex items-center gap-3 mt-1">
                  <span className="text-[10px] text-dim">SL <span className="text-red font-mono">₹{price(s.stop_loss)}</span></span>
                  <span className="text-[10px] text-dim">TP <span className="text-green font-mono">₹{price(s.take_profit)}</span></span>
                </div>
              </div>
            )
          })
        )}
      </div>
    </Panel>
  )
}

// ── Main Dashboard ────────────────────────────────────────────────────────────

export default function Dashboard() {
  const { data: equity }    = useSWR<EquityPoint[]>('/api/equity', fetcher, { refreshInterval: 30_000 })
  const { data: positions } = useSWR<PositionsResponse>('/api/positions', fetcher, { refreshInterval: 15_000 })
  const { data: trades }    = useSWR<TradesResponse>('/api/trades?source=paper', fetcher, { refreshInterval: 60_000 })
  const { snap, live }      = useLivePrices()

  const eqArr   = equity ?? []
  const latest  = eqArr[eqArr.length - 1]
  const capital = positions?.initial_capital ?? 500_000
  const totalReturn = latest ? (latest.equity - capital) / capital * 100 : 0
  const todayPnl = positions
    ? (positions.cash - positions.initial_capital)
      + (positions.positions ?? []).reduce((s, p) => s + p.unrealised_pnl, 0)
    : null
  const stats = trades?.stats

  // Equity chart — sample to ≤150 points
  const eqSample = eqArr.length > 150
    ? eqArr.filter((_, i) => i % Math.ceil(eqArr.length / 150) === 0)
    : eqArr
  const chartData = eqSample.map(p => ({ ts: p.ts.slice(0, 10), equity: p.equity }))
  const eqColor   = totalReturn >= 0 ? '#10b981' : '#f43f5e'

  // Tooltip styles
  const ttStyle = { background: '#161b27', border: '1px solid #252d3d', borderRadius: 8, fontSize: 11 }

  return (
    <div className="flex flex-col h-full p-4 gap-3 overflow-hidden">

      {/* Row 1: Market ticker */}
      <MarketTicker market={snap?.market ?? null} live={live} />

      {/* Row 2: KPIs */}
      <div className="grid grid-cols-3 md:grid-cols-6 gap-3 shrink-0">
        <KPI
          label="Portfolio"
          value={latest ? `₹${(latest.equity / 1000).toFixed(1)}k` : '—'}
          sub={pct(totalReturn)}
          up={totalReturn >= 0}
        />
        <KPI
          label="Today P&L"
          value={todayPnl != null ? pnl(todayPnl) : '—'}
          up={todayPnl != null ? todayPnl >= 0 : undefined}
        />
        <KPI
          label="Total Return"
          value={pct(totalReturn)}
          sub={latest ? inr(latest.equity) : undefined}
          up={totalReturn >= 0}
        />
        <KPI
          label="Win Rate"
          value={stats ? `${stats.win_rate.toFixed(1)}%` : '—'}
          sub={stats ? `${stats.wins}W / ${stats.losses}L` : undefined}
          up={stats ? stats.win_rate >= 50 : undefined}
        />
        <KPI
          label="Positions"
          value={String(positions?.positions.length ?? 0)}
          sub={positions ? `${((capital - (positions.cash ?? capital)) / capital * 100).toFixed(1)}% deployed` : undefined}
        />
        <KPI
          label="Total Trades"
          value={stats ? String(stats.total) : '—'}
          sub={stats ? `PF ${stats.profit_factor > 0 ? stats.profit_factor.toFixed(2) : '—'}` : undefined}
          up={stats ? stats.profit_factor >= 1 : undefined}
        />
      </div>

      {/* Row 3: Main content — fills remaining height */}
      <div className="flex-1 grid grid-cols-1 xl:grid-cols-[1fr_380px] gap-3 min-h-0 overflow-hidden">

        {/* Left column: equity curve (fixed) + universe (grows) */}
        <div className="flex flex-col gap-3 min-h-0 overflow-hidden">

          {/* Equity curve */}
          <Panel
            title="Equity Curve"
            right={<span className={clsx('font-mono', totalReturn >= 0 ? 'text-green' : 'text-red')}>{pct(totalReturn)}</span>}
            className="shrink-0"
          >
            {chartData.length > 1 ? (
              <div className="p-4">
                <ResponsiveContainer width="100%" height={160}>
                  <AreaChart data={chartData} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
                    <defs>
                      <linearGradient id="eqGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%"  stopColor={eqColor} stopOpacity={0.15} />
                        <stop offset="95%" stopColor={eqColor} stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid stroke="#252d3d" strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="ts" tick={{ fill: '#8892a4', fontSize: 9 }} tickLine={false} axisLine={false}
                           interval="preserveStartEnd" />
                    <YAxis tick={{ fill: '#8892a4', fontSize: 9 }} tickLine={false} axisLine={false}
                           width={48} tickFormatter={v => `${(v / 1000).toFixed(0)}k`} />
                    <ReferenceLine y={capital} stroke="#4b5563" strokeDasharray="4 2" />
                    <Tooltip formatter={(v: any) => [inr(Number(v)), 'Equity']} contentStyle={ttStyle}
                             labelStyle={{ color: '#8892a4' }} />
                    <Area type="monotone" dataKey="equity" stroke={eqColor} strokeWidth={2}
                          fill="url(#eqGrad)" dot={false} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <div className="flex items-center justify-center h-44 text-xs text-dim">
                No equity data — run <code className="mx-1 text-blue">python scripts/seed_dashboard_data.py</code>
              </div>
            )}
          </Panel>

          {/* Universe — takes all remaining height */}
          <div className="flex-1 min-h-0 overflow-hidden">
            <WatchlistPanel watchlist={snap?.watchlist ?? null} />
          </div>
        </div>

        {/* Right column: signals feed */}
        <SignalsFeed />
      </div>
    </div>
  )
}
