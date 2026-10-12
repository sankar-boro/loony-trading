import { useState } from 'react'
import useSWR from 'swr'
import { api, fetcher } from '../api'
import type { DeskAction, DeskEvent, DeskPosition, DeskResponse, SessionPhase } from '../types'
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine, CartesianGrid,
} from 'recharts'
import clsx from 'clsx'

const inr    = (n: number) => `₹${Math.abs(n).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
const pnlFmt = (n: number) => `${n >= 0 ? '+' : '-'}${inr(n)}`
const pr     = (n: number) => n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const signed = (n: number) => `${n < 0 ? '-' : ''}${inr(n)}`
const hhmm   = (iso: string) => iso.slice(11, 16)
const ttStyle = { background: '#161b27', border: '1px solid #252d3d', borderRadius: 8, fontSize: 13 }

const PHASE: Record<SessionPhase, { label: string; tone: string; hint: string }> = {
  pre_open:     { label: 'Pre-open',          tone: 'text-dim',   hint: 'Market opens at 09:15' },
  opening:      { label: 'Opening',           tone: 'text-amber', hint: 'Market open — entries start at the entry window' },
  entry_window: { label: 'Entry window',      tone: 'text-green', hint: 'New intraday entries allowed' },
  manage_only:  { label: 'Manage only',       tone: 'text-amber', hint: 'No new MIS entries — open trades still managed' },
  squareoff:    { label: 'Squareoff',         tone: 'text-red',   hint: 'MIS positions closed at 15:14' },
  closed:       { label: 'Closed',            tone: 'text-dim',   hint: 'Session over' },
  weekend:      { label: 'Weekend',           tone: 'text-dim',   hint: 'No trading today' },
  holiday:      { label: 'Exchange holiday',  tone: 'text-dim',   hint: 'No trading today' },
}

const EVENT_TONE: Record<string, string> = {
  entry: 'text-blue', exit: 'text-primary', block: 'text-dim', halt: 'text-red',
  flatten: 'text-amber', control: 'text-amber', error: 'text-red', heartbeat: 'text-amber',
  squareoff: 'text-amber',
}

// ── Building blocks ──────────────────────────────────────────────────────────

function Panel({ title, right, children, className }: {
  title: string; right?: React.ReactNode; children: React.ReactNode; className?: string
}) {
  return (
    <div className={clsx('bg-surface border border-border rounded-xl flex flex-col min-h-0', className)}>
      <div className="px-4 py-2.5 border-b border-border flex items-center gap-2 shrink-0">
        <span className="text-sm font-medium text-dim uppercase tracking-wide">{title}</span>
        <span className="ml-auto">{right}</span>
      </div>
      <div className="flex-1 min-h-0 overflow-auto">{children}</div>
    </div>
  )
}

function KPI({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: string }) {
  return (
    <div className="bg-surface border border-border rounded-xl px-4 py-3">
      <div className="text-[11px] text-dim uppercase tracking-wide mb-1">{label}</div>
      <div className={clsx('text-lg font-mono font-semibold', tone ?? 'text-primary')}>{value}</div>
      {sub && <div className="text-[12px] text-dim font-mono mt-0.5">{sub}</div>}
    </div>
  )
}

function Meter({ pct, tone }: { pct: number; tone: string }) {
  return (
    <div className="h-1.5 rounded-full bg-border overflow-hidden mt-1.5">
      <div className={clsx('h-full rounded-full transition-all', tone)} style={{ width: `${Math.min(100, Math.max(0, pct))}%` }} />
    </div>
  )
}

function Empty({ text }: { text: string }) {
  return <div className="h-full min-h-[80px] flex items-center justify-center text-sm text-dim">{text}</div>
}

// ── Session timeline: 09:15 → 15:30 with entry window and squareoff marked ──

function toMin(hm: string) { const [h, m] = hm.split(':').map(Number); return h * 60 + m }

function SessionBar({ d }: { d: DeskResponse }) {
  const s = d.session
  const start = toMin(s.market_open), end = toMin(s.market_close), span = end - start
  const pos = (hm: string) => ((toMin(hm) - start) / span) * 100
  const nowMin = toMin(hhmm(s.now))
  const nowPct = Math.min(100, Math.max(0, ((nowMin - start) / span) * 100))
  const showNow = s.trading_day && nowMin >= start && nowMin <= end
  return (
    <div>
      <div className="relative h-3 rounded-full bg-border overflow-hidden">
        <div className="absolute inset-y-0 bg-green/30"
             style={{ left: `${pos(s.entry_start)}%`, width: `${pos(s.entry_end) - pos(s.entry_start)}%` }} />
        <div className="absolute inset-y-0 bg-red/30"
             style={{ left: `${pos(s.squareoff)}%`, right: 0 }} />
        {showNow && <div className="absolute inset-y-0 w-0.5 bg-primary" style={{ left: `${nowPct}%` }} />}
      </div>
      <div className="relative h-4 text-[11px] font-mono text-dim mt-1">
        {/* entry_start sits too close to the open to label; the legend names it */}
        <span className="absolute left-0">{s.market_open}</span>
        <span className="absolute -translate-x-1/2" style={{ left: `${pos(s.entry_end)}%` }}>{s.entry_end}</span>
        <span className="absolute -translate-x-full pr-1.5" style={{ left: `${pos(s.squareoff)}%` }}>{s.squareoff}</span>
        <span className="absolute right-0">{s.market_close}</span>
      </div>
    </div>
  )
}

// ── Controls ─────────────────────────────────────────────────────────────────

const CONFIRM: Record<DeskAction, string> = {
  pause:   'Pause new entries? Open positions keep their stops and targets.',
  resume:  'Resume entries? This also clears a kill-switch or profit-lock halt for today.',
  flatten: 'Close EVERY open position at market now?',
}

function Controls({ d, onDone }: { d: DeskResponse; onDone: () => void }) {
  const [busy, setBusy] = useState<DeskAction | null>(null)
  const [error, setError] = useState('')
  const paused = d.guard.paused || !!d.control.paused
  const halted = d.guard.halted

  async function run(action: DeskAction) {
    if (!window.confirm(CONFIRM[action])) return
    setBusy(action); setError('')
    try { await api.intradayControl(action); onDone() }
    catch (e) { setError(String(e)) }
    finally { setBusy(null) }
  }

  const btn = 'px-3 py-1.5 rounded-lg text-sm font-medium border transition-colors disabled:opacity-40'
  return (
    <div className="flex items-center gap-2 flex-wrap">
      {paused || halted ? (
        <button className={clsx(btn, 'border-green/40 text-green hover:bg-green/10')}
                disabled={!!busy} onClick={() => run('resume')}>
          {busy === 'resume' ? 'Resuming…' : halted ? 'Clear halt & resume' : 'Resume entries'}
        </button>
      ) : (
        <button className={clsx(btn, 'border-amber/40 text-amber hover:bg-amber/10')}
                disabled={!!busy} onClick={() => run('pause')}>
          {busy === 'pause' ? 'Pausing…' : 'Pause entries'}
        </button>
      )}
      <button className={clsx(btn, 'border-red/40 text-red hover:bg-red/10')}
              disabled={!!busy || d.positions.length === 0} onClick={() => run('flatten')}>
        {busy === 'flatten' ? 'Flattening…' : 'Flatten all'}
      </button>
      {!d.bot.running && (
        <span className="text-[12px] text-dim">Bot not running — commands apply when it starts</span>
      )}
      {error && <span className="text-[12px] text-red">{error}</span>}
    </div>
  )
}

// ── Tables ───────────────────────────────────────────────────────────────────

function PositionsTable({ positions, exchangeStops, cooldowns }: {
  positions: DeskPosition[]; exchangeStops: boolean; cooldowns: Record<string, string>
}) {
  if (positions.length === 0) return <Empty text="Flat — no open positions" />
  return (
    <table className="w-full text-sm font-mono">
      <thead className="sticky top-0 bg-surface">
        <tr className="border-b border-border text-[11px] uppercase tracking-wide text-dim">
          {['Symbol', 'Side', 'Qty', 'Entry', 'LTP', 'Stop', 'Target', 'P&L', exchangeStops ? 'Broker stop' : ''].map(h => (
            <th key={h} className="text-left font-medium px-3 py-2 whitespace-nowrap">{h}</th>
          ))}
        </tr>
      </thead>
      <tbody className="divide-y divide-border/50">
        {positions.map(p => {
          const long = p.direction === 1
          return (
            <tr key={p.symbol + p.entry_time} className="hover:bg-white/3">
              <td className="px-3 py-2">
                <div className="font-semibold">{p.symbol}</div>
                <div className="text-[11px] text-dim">{p.strategy}{p.product ? ` · ${p.product}` : ''}</div>
              </td>
              <td className={clsx('px-3 py-2', long ? 'text-green' : 'text-red')}>{long ? 'LONG' : 'SHORT'}</td>
              <td className="px-3 py-2">{Math.round(p.size)}</td>
              <td className="px-3 py-2">{pr(p.entry_price)}</td>
              <td className="px-3 py-2">{pr(p.current_price)}</td>
              <td className="px-3 py-2 text-red">{pr(p.stop_loss)}</td>
              <td className="px-3 py-2 text-green">{pr(p.take_profit)}</td>
              <td className={clsx('px-3 py-2 font-semibold', p.unrealised_pnl >= 0 ? 'text-green' : 'text-red')}>
                {pnlFmt(p.unrealised_pnl)}
              </td>
              {exchangeStops && (
                <td className="px-3 py-2">
                  {p.stop_order_id
                    ? <span className="text-green" title={p.stop_order_id}>● held</span>
                    : <span className="text-red">● missing</span>}
                </td>
              )}
            </tr>
          )
        })}
      </tbody>
      {Object.keys(cooldowns).length > 0 && (
        <tfoot>
          <tr><td colSpan={9} className="px-3 py-2 text-[12px] text-dim border-t border-border">
            Cooling down after a stop-out: {Object.entries(cooldowns).map(([s, t]) => `${s} until ${hhmm(t)}`).join(', ')}
          </td></tr>
        </tfoot>
      )}
    </table>
  )
}

function TradesTable({ d }: { d: DeskResponse }) {
  if (d.trades.length === 0) return <Empty text="No closed trades today" />
  return (
    <table className="w-full text-sm font-mono">
      <thead className="sticky top-0 bg-surface">
        <tr className="border-b border-border text-[11px] uppercase tracking-wide text-dim">
          {['Time', 'Symbol', 'Side', 'Entry', 'Exit', 'Reason', 'P&L'].map(h => (
            <th key={h} className="text-left font-medium px-3 py-2">{h}</th>
          ))}
        </tr>
      </thead>
      <tbody className="divide-y divide-border/50">
        {[...d.trades].sort((a, b) => Date.parse(b.ts) - Date.parse(a.ts)).map((t, i) => (
          <tr key={i} className="hover:bg-white/3">
            <td className="px-3 py-2 text-dim">{new Date(t.ts).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Kolkata' })}</td>
            <td className="px-3 py-2">
              <div className="font-semibold">{t.symbol}</div>
              <div className="text-[11px] text-dim">{t.strategy}</div>
            </td>
            <td className={clsx('px-3 py-2', t.direction === 1 ? 'text-green' : 'text-red')}>{t.direction === 1 ? 'L' : 'S'}</td>
            <td className="px-3 py-2">{pr(t.entry_price)}</td>
            <td className="px-3 py-2">{pr(t.exit_price)}</td>
            <td className="px-3 py-2 text-dim">{t.reason}</td>
            <td className={clsx('px-3 py-2 font-semibold', t.pnl >= 0 ? 'text-green' : 'text-red')}>{pnlFmt(t.pnl)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function EventLog({ events }: { events: DeskEvent[] }) {
  if (events.length === 0) return <Empty text="No bot events today" />
  return (
    <ul className="divide-y divide-border/50 text-sm">
      {events.map((e, i) => (
        <li key={i} className="px-4 py-2 flex gap-3">
          <span className="font-mono text-dim shrink-0">{e.ts.slice(11, 19)}</span>
          <span className={clsx('font-mono text-[11px] uppercase w-16 shrink-0 pt-0.5', EVENT_TONE[e.kind] ?? 'text-dim')}>{e.kind}</span>
          <span className="text-primary/90 break-words min-w-0">{e.message}</span>
        </li>
      ))}
    </ul>
  )
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function IntradayDesk() {
  const { data: d, error, mutate } = useSWR<DeskResponse>('/api/intraday/desk', fetcher, { refreshInterval: 5_000 })

  if (error) return <div className="p-6 text-red">Could not load the desk: {String(error)}</div>
  if (!d) return <div className="p-6 text-dim animate-pulse">Loading…</div>

  const phase = PHASE[d.session.phase]
  const g = d.guard
  const lossTone = d.pnl.loss_used_pct >= 80 ? 'bg-red' : d.pnl.loss_used_pct >= 50 ? 'bg-amber' : 'bg-green'
  const tradeCapPct = g.max_trades_per_day ? (g.trades_today / g.max_trades_per_day) * 100 : 0
  const curve = d.curve.map(p => ({ t: hhmm(p.ts), total: p.total }))
  const lastTotal = curve.length ? curve[curve.length - 1].total : 0
  const curveColor = lastTotal >= 0 ? '#10b981' : '#f43f5e'

  const status = !d.bot.running ? { text: 'Bot stopped', tone: 'text-dim' }
    : g.halted ? { text: `Halted — ${g.halt_reason}`, tone: 'text-red' }
    : g.paused ? { text: 'Entries paused by operator', tone: 'text-amber' }
    : d.bot.feed_stale ? { text: `No market data for ${Math.round((d.bot.feed_age_sec ?? 0) / 60)} min`, tone: 'text-amber' }
    : { text: 'Trading', tone: 'text-green' }

  return (
    <div className="flex flex-col h-full p-4 gap-3 overflow-auto">

      {/* Header */}
      <div className="flex items-start gap-4 flex-wrap shrink-0">
        <div>
          <h1 className="text-lg font-semibold tracking-wide">Intraday Desk</h1>
          <div className="text-sm text-dim">
            {d.session.now.slice(0, 10)} · {hhmm(d.session.now)} IST
            {d.bot.mode && <> · <span className={d.bot.mode === 'live' ? 'text-red font-semibold' : 'text-blue'}>{d.bot.mode.toUpperCase()}</span></>}
          </div>
        </div>
        <div className="flex flex-col">
          <span className={clsx('text-base font-semibold', phase.tone)}>{phase.label}</span>
          <span className="text-[12px] text-dim">{phase.hint}</span>
        </div>
        <div className="flex flex-col">
          <span className={clsx('text-base font-semibold', status.tone)}>{status.text}</span>
          <span className="text-[12px] text-dim">
            {d.bot.last_tick_at ? `last tick ${Math.max(0, Math.round(d.bot.feed_age_sec ?? 0))}s ago` : 'no ticks yet'}
            {d.bot.exchange_stops && ' · broker-held stops on'}
          </span>
        </div>
        <div className="ml-auto"><Controls d={d} onDone={() => mutate()} /></div>
      </div>

      {/* Session timeline */}
      <div className="bg-surface border border-border rounded-xl px-4 pt-3 pb-1 shrink-0">
        <div className="flex text-[12px] text-dim mb-2 gap-4 flex-wrap">
          <span><span className="inline-block w-2 h-2 rounded-sm bg-green/50 mr-1" />entry window {d.session.entry_start}–{d.session.entry_end}</span>
          <span><span className="inline-block w-2 h-2 rounded-sm bg-red/50 mr-1" />MIS squareoff</span>
          {d.session.trading_day && d.session.mins_to_squareoff > 0 && (
            <span className="ml-auto font-mono">
              {d.session.mins_to_entry_end > 0 && `${d.session.mins_to_entry_end}m to last entry · `}
              {d.session.mins_to_squareoff}m to squareoff
            </span>
          )}
        </div>
        <SessionBar d={d} />
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-2 shrink-0">
        <KPI label="Day P&L" value={pnlFmt(d.pnl.day)} tone={d.pnl.day >= 0 ? 'text-green' : 'text-red'}
             sub={`${pnlFmt(d.pnl.realised)} booked · ${pnlFmt(d.pnl.unrealised)} open`} />
        <div className="bg-surface border border-border rounded-xl px-4 py-3">
          <div className="text-[11px] text-dim uppercase tracking-wide mb-1">Loss budget used</div>
          <div className="text-lg font-mono font-semibold">{d.pnl.loss_used_pct.toFixed(0)}%</div>
          <div className="text-[12px] text-dim font-mono">kill switch at −{inr(d.pnl.loss_limit)}</div>
          <Meter pct={d.pnl.loss_used_pct} tone={lossTone} />
        </div>
        <div className="bg-surface border border-border rounded-xl px-4 py-3">
          <div className="text-[11px] text-dim uppercase tracking-wide mb-1">Entries today</div>
          <div className="text-lg font-mono font-semibold">{g.trades_today}{g.max_trades_per_day ? ` / ${g.max_trades_per_day}` : ''}</div>
          <div className="text-[12px] text-dim font-mono">max {g.max_trades_per_symbol || '∞'} per symbol</div>
          <Meter pct={tradeCapPct} tone={tradeCapPct >= 100 ? 'bg-red' : 'bg-blue'} />
        </div>
        <KPI label="Open positions" value={String(d.positions.length)}
             sub={d.bot.exchange_stops ? `${d.positions.filter(p => p.stop_order_id).length} with broker stop` : undefined} />
        <KPI label="Closed trades" value={String(d.trades.length)}
             sub={d.trades.length ? `${d.trades.filter(t => t.pnl > 0).length} winners` : undefined} />
      </div>

      {/* P&L curve + per strategy */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-3 shrink-0">
        <Panel title="P&L today" className="xl:col-span-2"
               right={d.pnl.profit_lock > 0 && <span className="text-[12px] text-dim font-mono">profit lock +{inr(d.pnl.profit_lock)}</span>}>
          {curve.length > 1 ? (
            <div className="p-3">
              <ResponsiveContainer width="100%" height={180}>
                <AreaChart data={curve} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                  <CartesianGrid stroke="#252d3d" strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="t" tick={{ fill: '#8892a4', fontSize: 11 }} tickLine={false} axisLine={false}
                         interval="preserveStartEnd" minTickGap={40} />
                  <YAxis tick={{ fill: '#8892a4', fontSize: 11 }} tickLine={false} axisLine={false} width={56}
                         tickFormatter={v => signed(v)} />
                  <ReferenceLine y={0} stroke="#4b5563" />
                  <ReferenceLine y={-d.pnl.loss_limit} stroke="#f43f5e" strokeDasharray="4 2"
                                 label={{ value: 'kill switch', fill: '#f43f5e', fontSize: 11, position: 'insideBottomRight' }} />
                  {d.pnl.profit_lock > 0 && <ReferenceLine y={d.pnl.profit_lock} stroke="#10b981" strokeDasharray="4 2" />}
                  <Tooltip formatter={(v: any) => [pnlFmt(Number(v)), 'Day P&L']} contentStyle={ttStyle} />
                  <Area type="monotone" dataKey="total" stroke={curveColor} fill={curveColor} fillOpacity={0.12}
                        strokeWidth={2} dot={false} isAnimationActive={false} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          ) : <Empty text="The curve fills in minute by minute while the bot runs" />}
        </Panel>
        <Panel title="By strategy">
          {d.by_strategy.length === 0 ? <Empty text="No closed trades yet" /> : (
            <table className="w-full text-sm font-mono">
              <tbody className="divide-y divide-border/50">
                {d.by_strategy.map(s => (
                  <tr key={s.strategy}>
                    <td className="px-3 py-2">{s.strategy}</td>
                    <td className="px-3 py-2 text-dim">{s.wins}/{s.trades}</td>
                    <td className={clsx('px-3 py-2 text-right font-semibold', s.pnl >= 0 ? 'text-green' : 'text-red')}>{pnlFmt(s.pnl)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>
      </div>

      {/* Positions */}
      <Panel title="Open positions" className="shrink-0">
        <PositionsTable positions={d.positions} exchangeStops={d.bot.exchange_stops} cooldowns={g.cooldowns ?? {}} />
      </Panel>

      {/* Trades + events */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-3 min-h-[280px]">
        <Panel title="Today's trades"><TradesTable d={d} /></Panel>
        <Panel title="Bot events"><EventLog events={d.events} /></Panel>
      </div>
    </div>
  )
}
