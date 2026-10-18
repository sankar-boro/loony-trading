import { useState } from 'react'
import useSWR from 'swr'
import { fetcher } from '../api'
import type { CompositeSignal, SignalPerformance } from '../types'
import clsx from 'clsx'

const DIRECTIONS = ['all', 'bullish', 'bearish', 'watch', 'no_signal'] as const
type Dir = typeof DIRECTIONS[number]

// "30m" not "15m" as the intraday option — Upstox returns HTTP 400 for
// 5m/15m on this account (see docs/appendix/intraday-audit.md §5); 30m/1h work.
const TIMEFRAMES = ['1d', '30m', '1h'] as const
type Timeframe = typeof TIMEFRAMES[number]
const TF_LABEL: Record<string, string> = { '1d': 'Daily', '30m': '30 min', '1h': '1 hour' }

const DIR_LABEL: Record<string, string> = {
  bullish: 'Bullish', bearish: 'Bearish', watch: 'Watch', no_signal: 'No Signal',
}
const DIR_CLASS: Record<string, string> = {
  bullish: 'bg-green/15 text-green', bearish: 'bg-red/15 text-red',
  watch: 'bg-amber-500/15 text-amber-400', no_signal: 'bg-white/5 text-dim',
}
const WEIGHTS: Record<string, number> = {
  catalyst: 0.25, technical: 0.20, momentum: 0.15, volume: 0.15,
  historical: 0.10, regime: 0.10, risk: 0.05,
}
const COMPONENT_LABEL: Record<string, string> = {
  catalyst: 'Catalyst', technical: 'Technical', momentum: 'Momentum', volume: 'Volume',
  historical: 'Historical', regime: 'Market Regime', risk: 'Risk Quality',
}

function DirBadge({ direction }: { direction: string }) {
  return (
    <span className={clsx('px-1.5 py-0.5 rounded text-[11px] font-bold', DIR_CLASS[direction])}>
      {DIR_LABEL[direction] ?? direction}
    </span>
  )
}

function BreakdownPanel({ signal }: { signal: CompositeSignal }) {
  const rows = Object.entries(signal.components).map(([key, value]) => ({
    key, label: COMPONENT_LABEL[key] ?? key, value, weight: WEIGHTS[key] ?? 0,
    contribution: value * (WEIGHTS[key] ?? 0),
  }))

  return (
    <div className="bg-surface border border-border rounded-xl p-4 flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-base font-semibold flex items-center gap-1.5">
            {signal.symbol}
            <span className="px-1.5 py-0.5 rounded text-[11px] font-mono bg-white/5 text-dim">
              {signal.timeframe}
            </span>
          </div>
          <div className="text-[12px] text-dim font-mono">
            {new Date(signal.timestamp).toLocaleString('en-IN')}
          </div>
        </div>
        <DirBadge direction={signal.direction} />
      </div>

      <div className="flex items-baseline gap-3">
        <span className="text-4xl font-mono font-bold">{signal.score.toFixed(1)}</span>
        <span className="text-sm text-dim">score · {signal.confidence.toFixed(0)}% confidence</span>
      </div>

      <div>
        <div className="text-[11px] text-dim uppercase tracking-wide mb-2">
          Why {signal.score.toFixed(0)}?
        </div>
        <div className="flex flex-col gap-1.5">
          {rows.map(r => (
            <div key={r.key} className="flex items-center gap-2 text-sm">
              <span className="w-24 text-dim shrink-0">{r.label}</span>
              <div className="flex-1 h-2 bg-white/5 rounded overflow-hidden">
                <div className="h-full bg-blue" style={{ width: `${Math.min(100, r.value)}%` }} />
              </div>
              <span className="w-10 text-right font-mono">{r.value.toFixed(0)}</span>
              <span className="w-16 text-right font-mono text-dim">+{r.contribution.toFixed(1)}</span>
            </div>
          ))}
          <div className="flex items-center gap-2 text-sm pt-1.5 border-t border-border mt-1">
            <span className="w-24 font-semibold">Total</span>
            <div className="flex-1" />
            <span className="w-10" />
            <span className="w-16 text-right font-mono font-semibold">{signal.score.toFixed(1)}</span>
          </div>
        </div>
      </div>

      {signal.trade_setup && (
        <div>
          <div className="text-[11px] text-dim uppercase tracking-wide mb-2">Trade Setup</div>
          <div className="grid grid-cols-2 gap-2 text-sm">
            <div className="bg-white/5 rounded-lg px-3 py-2">
              <div className="text-dim text-[11px] uppercase">Entry Zone</div>
              <div className="font-mono">
                ₹{signal.trade_setup.entry_low.toFixed(2)}–{signal.trade_setup.entry_high.toFixed(2)}
              </div>
            </div>
            <div className="bg-white/5 rounded-lg px-3 py-2">
              <div className="text-dim text-[11px] uppercase">Stop Loss</div>
              <div className="font-mono text-red">₹{signal.trade_setup.stop_loss.toFixed(2)}</div>
            </div>
            <div className="bg-white/5 rounded-lg px-3 py-2">
              <div className="text-dim text-[11px] uppercase">Target 1</div>
              <div className="font-mono text-green">₹{signal.trade_setup.target_1.toFixed(2)}</div>
            </div>
            <div className="bg-white/5 rounded-lg px-3 py-2">
              <div className="text-dim text-[11px] uppercase">Risk/Reward</div>
              <div className="font-mono">{signal.trade_setup.risk_reward?.toFixed(2) ?? '—'}</div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

const pct = (v: number | null, signed = true) =>
  v === null ? '—' : `${signed && v > 0 ? '+' : ''}${v.toFixed(2)}%`

function TrackRecord() {
  const [days, setDays] = useState(90)
  const { data: p, isLoading } = useSWR<SignalPerformance>(`/api/signals/performance?days=${days}`, fetcher,
                                                           { refreshInterval: 300_000 })
  const card = 'bg-surface border border-border rounded-xl'
  const head = 'text-left px-3 py-2 text-[11px] uppercase tracking-wide text-dim font-medium whitespace-nowrap'
  return (
    <div className="flex-1 overflow-auto min-h-0 flex flex-col gap-3">
      <div className="flex items-center gap-2 text-sm">
        {[30, 90, 180].map(d => (
          <button key={d} onClick={() => setDays(d)}
                  className={clsx('px-3 py-1 rounded-lg border',
                    days === d ? 'bg-blue/15 text-blue border-blue/30' : 'border-border text-dim hover:text-primary')}>
            {d} days
          </button>
        ))}
        {p && <span className="text-dim ml-2">{p.evaluated} signals evaluated · {p.complete} with all horizons</span>}
      </div>
      {isLoading && <span className="text-sm text-dim animate-pulse">Loading…</span>}
      {p && p.evaluated === 0 && (
        <div className={clsx(card, 'p-8 text-center text-dim')}>
          No outcomes yet. They are recorded every weekday at 16:30 IST, a day after each signal
          (<code className="text-blue">python scripts/evaluate_signals.py</code> to run it now).
        </div>
      )}
      {p && p.evaluated > 0 && (
        <>
          <div className={card}>
            <div className="px-4 py-2.5 border-b border-border text-sm text-dim">
              Returns after the signal day's close. Bullish and bearish are direction-adjusted;
              <b className="text-primary"> excess</b> is against the baseline (all evaluated signals:
              {' '}5d {pct(p.baseline.ret_5d)}, 20d {pct(p.baseline.ret_20d)}).
            </div>
            <table className="w-full text-sm font-mono">
              <thead><tr className="border-b border-border">
                {['Direction', 'N', 'Avg 1d', 'Avg 5d', 'Hit 5d', 'Excess 5d', 'Avg 20d', 'Excess 20d', 'Setups T / S / E'].map(h =>
                  <th key={h} className={head}>{h}</th>)}
              </tr></thead>
              <tbody className="divide-y divide-border/50">
                {p.by_direction.filter(d => d.count > 0).map(d => (
                  <tr key={d.direction}>
                    <td className="px-3 py-2"><DirBadge direction={d.direction} /></td>
                    <td className="px-3 py-2 text-dim">{d.count}</td>
                    <td className="px-3 py-2">{pct(d.avg_1d)}</td>
                    <td className="px-3 py-2">{pct(d.avg_5d)}</td>
                    <td className="px-3 py-2">{d.hit_5d === null ? '—' : `${d.hit_5d.toFixed(0)}%`}</td>
                    <td className={clsx('px-3 py-2 font-semibold', d.excess_5d === null ? 'text-dim'
                      : d.excess_5d >= 0 ? 'text-green' : 'text-red')}>{pct(d.excess_5d)}</td>
                    <td className="px-3 py-2">{pct(d.avg_20d)}</td>
                    <td className={clsx('px-3 py-2', d.excess_20d === null ? 'text-dim'
                      : d.excess_20d >= 0 ? 'text-green' : 'text-red')}>{pct(d.excess_20d)}</td>
                    <td className="px-3 py-2 text-dim">
                      {d.setups.target} / {d.setups.stop} / {d.setups.expired}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
            <div className={card}>
              <div className="px-4 py-2.5 border-b border-border text-sm text-dim">
                Bullish + bearish by score — does a higher score do better?
              </div>
              <table className="w-full text-sm font-mono">
                <thead><tr className="border-b border-border">
                  {['Score', 'N', 'Avg 5d', 'Hit 5d'].map(h => <th key={h} className={head}>{h}</th>)}
                </tr></thead>
                <tbody className="divide-y divide-border/50">
                  {p.by_score.map(r => (
                    <tr key={r.band}>
                      <td className="px-3 py-2">{r.band}</td>
                      <td className="px-3 py-2 text-dim">{r.count}</td>
                      <td className={clsx('px-3 py-2', (r.avg_5d ?? 0) >= 0 ? 'text-green' : 'text-red')}>{pct(r.avg_5d)}</td>
                      <td className="px-3 py-2">{r.hit_5d === null ? '—' : `${r.hit_5d.toFixed(0)}%`}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className={card}>
              <div className="px-4 py-2.5 border-b border-border text-sm text-dim">
                Component score vs direction-adjusted 5-day return (correlation)
              </div>
              <div className="p-3 space-y-2">
                {p.components.map(c => (
                  <div key={c.component} className="flex items-center gap-3 text-sm">
                    <span className="w-28 text-dim">{COMPONENT_LABEL[c.component] ?? c.component}</span>
                    <div className="flex-1 h-2 bg-border rounded-full relative overflow-hidden">
                      {c.corr_5d !== null && (
                        <div className={clsx('absolute inset-y-0', c.corr_5d >= 0 ? 'bg-green/70 left-1/2' : 'bg-red/70 right-1/2')}
                             style={{ width: `${Math.min(Math.abs(c.corr_5d), 1) * 50}%` }} />
                      )}
                      <div className="absolute inset-y-0 left-1/2 w-px bg-dim/50" />
                    </div>
                    <span className="w-14 text-right font-mono">{c.corr_5d === null ? '—' : c.corr_5d.toFixed(2)}</span>
                  </div>
                ))}
                <div className="text-[11px] text-dim pt-1">Needs at least 10 bullish/bearish signals with a 5-day result.</div>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  )
}

export default function Signals() {
  const [view, setView] = useState<'live' | 'record'>('live')
  const [filter, setFilter] = useState<Dir>('all')
  const [timeframe, setTimeframe] = useState<Timeframe>('1d')
  const [selectedId, setSelectedId] = useState<number | null>(null)

  const { data: signals, isLoading } = useSWR<CompositeSignal[]>(
    (() => {
      const q = new URLSearchParams({ timeframe })
      if (filter !== 'all') q.set('direction', filter)
      return `/api/signals/composite?${q.toString()}`
    })(),
    fetcher, { refreshInterval: 60_000 },
  )
  const { data: detail } = useSWR<CompositeSignal>(
    selectedId ? `/api/signals/composite/${selectedId}` : null, fetcher,
  )

  const sorted = [...(signals ?? [])].sort((a, b) => b.score - a.score)

  return (
    <div className="flex flex-col h-full p-4 gap-3 overflow-hidden">
      <div className="flex items-center gap-3 shrink-0 flex-wrap">
        <h1 className="text-lg font-semibold tracking-wide">Signals</h1>
        <span className="text-sm text-dim">
          Multi-factor composite — Catalyst 25% · Technical 20% · Momentum 15% ·
          Volume 15% · Historical 10% · Regime 10% · Risk 5%
        </span>
        <div className="ml-auto flex gap-1.5">
          {(['live', 'record'] as const).map(v => (
            <button key={v} onClick={() => setView(v)}
                    className={clsx('px-3 py-1.5 rounded-lg text-sm transition-colors',
                      view === v ? 'bg-blue text-white font-medium' : 'bg-surface border border-border text-dim hover:text-primary')}>
              {v === 'live' ? 'Live signals' : 'Track record'}
            </button>
          ))}
        </div>
      </div>

      {view === 'record' ? <TrackRecord /> : <>

      <div className="flex items-center gap-3 shrink-0 flex-wrap">
        <div className="flex gap-1.5">
          {DIRECTIONS.map(d => (
            <button
              key={d} onClick={() => setFilter(d)}
              className={clsx('px-3 py-1.5 rounded-lg text-sm capitalize transition-colors',
                filter === d
                  ? 'bg-blue text-white font-medium'
                  : 'bg-surface border border-border text-dim hover:text-primary')}
            >
              {d === 'all' ? 'All' : DIR_LABEL[d]}
            </button>
          ))}
        </div>
        <div className="w-px h-5 bg-border" />
        <div className="flex gap-1.5">
          {TIMEFRAMES.map(tf => (
            <button
              key={tf} onClick={() => { setTimeframe(tf); setSelectedId(null) }}
              className={clsx('px-3 py-1.5 rounded-lg text-sm transition-colors',
                timeframe === tf
                  ? 'bg-blue/15 text-blue border border-blue/30 font-medium'
                  : 'bg-surface border border-border text-dim hover:text-primary')}
            >
              {TF_LABEL[tf]}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 grid grid-cols-1 lg:grid-cols-[1fr_360px] gap-3 min-h-0 overflow-hidden">
        <div className="bg-surface border border-border rounded-xl flex flex-col min-h-0 overflow-hidden">
          {isLoading && <span className="text-sm text-dim animate-pulse p-4">Loading…</span>}
          {!isLoading && sorted.length === 0 && (
            <div className="flex flex-col items-center justify-center flex-1 gap-2 text-dim px-6 text-center">
              <span className="text-3xl opacity-30">◇</span>
              <span className="text-base">No {TF_LABEL[timeframe].toLowerCase()} signals in this category</span>
              {timeframe !== '1d' && (
                <span className="text-sm">Run a scan from the <b className="text-primary">Intraday</b> page to populate this timeframe.</span>
              )}
            </div>
          )}
          {sorted.length > 0 && (
            <div className="flex-1 overflow-auto min-h-0">
              <table className="w-full text-sm font-mono min-w-[520px]">
                <thead className="sticky top-0 bg-surface z-10">
                  <tr className="border-b border-border">
                    {['Symbol', 'Direction', 'Score', 'Confidence', 'Time'].map(h => (
                      <th key={h} className="text-left px-4 py-2.5 text-[11px] uppercase tracking-wide text-dim font-medium whitespace-nowrap">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/50">
                  {sorted.map(s => (
                    <tr
                      key={s.id} onClick={() => setSelectedId(s.id)}
                      className={clsx('hover:bg-white/3 transition-colors cursor-pointer',
                        selectedId === s.id && 'bg-blue/10')}
                    >
                      <td className="px-4 py-2 font-semibold">{s.symbol}</td>
                      <td className="px-4 py-2"><DirBadge direction={s.direction} /></td>
                      <td className="px-4 py-2">{s.score.toFixed(1)}</td>
                      <td className="px-4 py-2">{s.confidence.toFixed(0)}%</td>
                      <td className="px-4 py-2 text-dim">
                        {new Date(s.timestamp).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="overflow-y-auto min-h-0">
          {detail ? <BreakdownPanel signal={detail} /> : (
            <div className="bg-surface border border-border rounded-xl flex flex-col items-center justify-center h-full gap-2 text-dim p-8">
              <span className="text-3xl opacity-30">◈</span>
              <span className="text-base text-center">Select a signal to see its score breakdown</span>
            </div>
          )}
        </div>
      </div>
      </>}
    </div>
  )
}
