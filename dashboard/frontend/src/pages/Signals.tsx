import { useState } from 'react'
import useSWR from 'swr'
import { fetcher } from '../api'
import type { CompositeSignal } from '../types'
import clsx from 'clsx'

const DIRECTIONS = ['all', 'bullish', 'bearish', 'watch', 'no_signal'] as const
type Dir = typeof DIRECTIONS[number]

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
    <span className={clsx('px-1.5 py-0.5 rounded text-[9px] font-bold', DIR_CLASS[direction])}>
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
          <div className="text-sm font-semibold">{signal.symbol}</div>
          <div className="text-[10px] text-dim font-mono">
            {new Date(signal.timestamp).toLocaleString('en-IN')}
          </div>
        </div>
        <DirBadge direction={signal.direction} />
      </div>

      <div className="flex items-baseline gap-3">
        <span className="text-3xl font-mono font-bold">{signal.score.toFixed(1)}</span>
        <span className="text-xs text-dim">score · {signal.confidence.toFixed(0)}% confidence</span>
      </div>

      <div>
        <div className="text-[9px] text-dim uppercase tracking-wide mb-2">
          Why {signal.score.toFixed(0)}?
        </div>
        <div className="flex flex-col gap-1.5">
          {rows.map(r => (
            <div key={r.key} className="flex items-center gap-2 text-xs">
              <span className="w-24 text-dim shrink-0">{r.label}</span>
              <div className="flex-1 h-2 bg-white/5 rounded overflow-hidden">
                <div className="h-full bg-blue" style={{ width: `${Math.min(100, r.value)}%` }} />
              </div>
              <span className="w-10 text-right font-mono">{r.value.toFixed(0)}</span>
              <span className="w-16 text-right font-mono text-dim">+{r.contribution.toFixed(1)}</span>
            </div>
          ))}
          <div className="flex items-center gap-2 text-xs pt-1.5 border-t border-border mt-1">
            <span className="w-24 font-semibold">Total</span>
            <div className="flex-1" />
            <span className="w-10" />
            <span className="w-16 text-right font-mono font-semibold">{signal.score.toFixed(1)}</span>
          </div>
        </div>
      </div>

      {signal.trade_setup && (
        <div>
          <div className="text-[9px] text-dim uppercase tracking-wide mb-2">Trade Setup</div>
          <div className="grid grid-cols-2 gap-2 text-xs">
            <div className="bg-white/5 rounded-lg px-3 py-2">
              <div className="text-dim text-[9px] uppercase">Entry Zone</div>
              <div className="font-mono">
                ₹{signal.trade_setup.entry_low.toFixed(2)}–{signal.trade_setup.entry_high.toFixed(2)}
              </div>
            </div>
            <div className="bg-white/5 rounded-lg px-3 py-2">
              <div className="text-dim text-[9px] uppercase">Stop Loss</div>
              <div className="font-mono text-red">₹{signal.trade_setup.stop_loss.toFixed(2)}</div>
            </div>
            <div className="bg-white/5 rounded-lg px-3 py-2">
              <div className="text-dim text-[9px] uppercase">Target 1</div>
              <div className="font-mono text-green">₹{signal.trade_setup.target_1.toFixed(2)}</div>
            </div>
            <div className="bg-white/5 rounded-lg px-3 py-2">
              <div className="text-dim text-[9px] uppercase">Risk/Reward</div>
              <div className="font-mono">{signal.trade_setup.risk_reward?.toFixed(2) ?? '—'}</div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default function Signals() {
  const [filter, setFilter] = useState<Dir>('all')
  const [selectedId, setSelectedId] = useState<number | null>(null)

  const { data: signals, isLoading } = useSWR<CompositeSignal[]>(
    `/api/signals/composite${filter !== 'all' ? `?direction=${filter}` : ''}`,
    fetcher, { refreshInterval: 60_000 },
  )
  const { data: detail } = useSWR<CompositeSignal>(
    selectedId ? `/api/signals/composite/${selectedId}` : null, fetcher,
  )

  const sorted = [...(signals ?? [])].sort((a, b) => b.score - a.score)

  return (
    <div className="flex flex-col h-full p-4 gap-3 overflow-hidden">
      <div className="flex items-center gap-3 shrink-0 flex-wrap">
        <h1 className="text-base font-semibold tracking-wide">Signals</h1>
        <span className="text-xs text-dim">
          Multi-factor composite — Catalyst 25% · Technical 20% · Momentum 15% ·
          Volume 15% · Historical 10% · Regime 10% · Risk 5%
        </span>
      </div>

      <div className="flex gap-1.5 shrink-0">
        {DIRECTIONS.map(d => (
          <button
            key={d} onClick={() => setFilter(d)}
            className={clsx('px-3 py-1.5 rounded-lg text-xs capitalize transition-colors',
              filter === d
                ? 'bg-blue text-white font-medium'
                : 'bg-surface border border-border text-dim hover:text-primary')}
          >
            {d === 'all' ? 'All' : DIR_LABEL[d]}
          </button>
        ))}
      </div>

      <div className="flex-1 grid grid-cols-1 lg:grid-cols-[1fr_360px] gap-3 min-h-0 overflow-hidden">
        <div className="bg-surface border border-border rounded-xl flex flex-col min-h-0 overflow-hidden">
          {isLoading && <span className="text-xs text-dim animate-pulse p-4">Loading…</span>}
          {!isLoading && sorted.length === 0 && (
            <div className="flex flex-col items-center justify-center flex-1 gap-2 text-dim">
              <span className="text-2xl opacity-30">◇</span>
              <span className="text-sm">No signals in this category</span>
            </div>
          )}
          {sorted.length > 0 && (
            <div className="flex-1 overflow-auto min-h-0">
              <table className="w-full text-xs font-mono min-w-[520px]">
                <thead className="sticky top-0 bg-surface z-10">
                  <tr className="border-b border-border">
                    {['Symbol', 'Direction', 'Score', 'Confidence', 'Time'].map(h => (
                      <th key={h} className="text-left px-4 py-2.5 text-[9px] uppercase tracking-wide text-dim font-medium whitespace-nowrap">
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
              <span className="text-2xl opacity-30">◈</span>
              <span className="text-sm text-center">Select a signal to see its score breakdown</span>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
