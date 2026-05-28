import useSWR from 'swr'
import { fetcher } from '../api'
import type { PositionsResponse } from '../types'
import clsx from 'clsx'

const fmt     = (n: number) => `₹${Math.abs(n).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
const pnlFmt  = (n: number) => `${n >= 0 ? '+' : '-'}${fmt(n)}`
const pct     = (n: number) => `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`
const fmtPrc  = (n: number) => n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

// ── Position Card ──────────────────────────────────────────────────────────────

function PositionCard({ p }: { p: PositionsResponse['positions'][0] }) {
  const pnlPct = p.entry_price
    ? p.unrealised_pnl / (p.entry_price * Math.abs(p.size)) * 100 : 0

  // Progress bar: how far price is from SL vs TP
  const range = Math.abs(p.take_profit - p.stop_loss)
  const progress = range > 0
    ? Math.min(1, Math.max(0,
        (p.current_price - p.stop_loss) / range
      ))
    : 0.5

  return (
    <div className="bg-surface border border-border rounded-xl p-5 space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-base font-semibold font-mono">{p.symbol}</span>
          <span className={clsx(
            'text-xs font-semibold px-2 py-0.5 rounded',
            p.direction === 1 ? 'bg-green/10 text-green' : 'bg-red/10 text-red',
          )}>
            {p.direction === 1 ? '▲ LONG' : '▼ SHORT'}
          </span>
        </div>
        <span className={clsx(
          'text-xl font-mono font-bold',
          p.unrealised_pnl >= 0 ? 'text-green' : 'text-red',
        )}>
          {pnlFmt(p.unrealised_pnl)}
        </span>
      </div>

      {/* Metrics */}
      <div className="grid grid-cols-3 gap-3 text-xs font-mono">
        <div>
          <div className="text-dim mb-0.5">Qty</div>
          <div className="text-primary font-medium">{Math.round(p.size)}</div>
        </div>
        <div>
          <div className="text-dim mb-0.5">Entry ₹</div>
          <div className="text-primary">{fmtPrc(p.entry_price)}</div>
        </div>
        <div>
          <div className="text-dim mb-0.5">CMP ₹</div>
          <div className={clsx(
            'font-medium',
            p.current_price >= p.entry_price ? 'text-green' : 'text-red',
          )}>{fmtPrc(p.current_price)}</div>
        </div>
        <div>
          <div className="text-dim mb-0.5">P&L %</div>
          <div className={pnlPct >= 0 ? 'text-green' : 'text-red'}>{pct(pnlPct)}</div>
        </div>
        <div>
          <div className="text-dim mb-0.5">Stop Loss</div>
          <div className="text-red">{fmtPrc(p.stop_loss)}</div>
        </div>
        <div>
          <div className="text-dim mb-0.5">Take Profit</div>
          <div className="text-green">{fmtPrc(p.take_profit)}</div>
        </div>
      </div>

      {/* SL ─── price ─── TP progress bar */}
      <div>
        <div className="flex justify-between text-xs text-dim mb-1">
          <span>SL {fmtPrc(p.stop_loss)}</span>
          <span>TP {fmtPrc(p.take_profit)}</span>
        </div>
        <div className="h-2 rounded-full bg-border overflow-hidden relative">
          <div
            className={clsx('h-full rounded-full', p.unrealised_pnl >= 0 ? 'bg-green' : 'bg-red')}
            style={{ width: `${progress * 100}%` }}
          />
        </div>
      </div>

      {/* Strategy tag + entry time */}
      <div className="flex items-center justify-between">
        <span className="text-xs bg-blue/10 text-blue px-2 py-0.5 rounded font-mono">
          {p.strategy}
        </span>
        <span className="text-xs text-dim font-mono">{p.entry_time}</span>
      </div>
    </div>
  )
}

// ── Main ───────────────────────────────────────────────────────────────────────

export default function Positions() {
  const { data, isLoading } = useSWR<PositionsResponse>(
    '/api/positions', fetcher, { refreshInterval: 10_000 },
  )

  const positions   = data?.positions ?? []
  const signalLog   = data?.signal_log ?? []
  const totalUnreal = positions.reduce((s, p) => s + p.unrealised_pnl, 0)
  const capital     = data?.initial_capital ?? 500_000
  const cash        = data?.cash ?? capital
  const deployed    = capital > 0 ? ((capital - cash) / capital) * 100 : 0

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Positions</h1>
        <div className="flex items-center gap-3">
          {isLoading && <span className="text-xs text-dim animate-pulse">Refreshing…</span>}
          {data && (
            <span className="text-xs text-dim font-mono">
              Updated {new Date(data.saved_at * 1000).toLocaleTimeString('en-IN')}
            </span>
          )}
        </div>
      </div>

      {/* Portfolio exposure bar */}
      <div className="bg-surface border border-border rounded-xl p-5">
        <div className="flex items-center justify-between text-sm mb-3">
          <span className="font-medium">Portfolio Exposure</span>
          <div className="flex items-center gap-4 text-xs font-mono">
            <span>
              <span className="text-dim">Deployed: </span>
              <span className="text-amber">{deployed.toFixed(1)}%</span>
            </span>
            <span>
              <span className="text-dim">Cash: </span>
              <span className="text-primary">₹{cash.toLocaleString('en-IN', { maximumFractionDigits: 0 })}</span>
            </span>
            {positions.length > 0 && (
              <span>
                <span className="text-dim">Unrealised: </span>
                <span className={totalUnreal >= 0 ? 'text-green' : 'text-red'}>
                  {pnlFmt(totalUnreal)}
                </span>
              </span>
            )}
          </div>
        </div>
        <div className="h-3 rounded-full bg-border overflow-hidden">
          <div
            className="h-full rounded-full bg-amber transition-all"
            style={{ width: `${Math.min(100, deployed)}%` }}
          />
        </div>
        <div className="flex justify-between text-xs text-dim mt-1.5 font-mono">
          <span>0%</span>
          <span>{positions.length} position{positions.length !== 1 ? 's' : ''}</span>
          <span>100%</span>
        </div>
      </div>

      {/* Position cards */}
      {positions.length > 0 ? (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {positions.map((p, i) => (
            <PositionCard key={i} p={p} />
          ))}
        </div>
      ) : (
        <div className="bg-surface border border-border rounded-xl p-10 text-center text-dim text-sm">
          {data ? 'No open positions.' : 'Bot not running — no position data.'}
        </div>
      )}

      {/* Signal log */}
      <div className="bg-surface border border-border rounded-xl overflow-hidden">
        <div className="px-5 py-3 border-b border-border text-sm font-medium flex items-center justify-between">
          <span>Signal Log</span>
          <span className="text-xs text-dim">{Math.min(signalLog.length, 50)} events</span>
        </div>
        {signalLog.length > 0 ? (
          <div className="divide-y divide-border max-h-96 overflow-y-auto">
            {[...signalLog].reverse().slice(0, 50).map((s, i) => {
              const isBuy   = s.type === 'BUY'
              const isSell  = s.type === 'SELL'
              const isClose = s.type === 'CLOSE'
              return (
                <div key={i} className="px-5 py-2.5 flex items-center gap-3 hover:bg-border/20 transition-colors">
                  <span className="text-xs text-dim font-mono w-20 shrink-0">{s.time}</span>
                  <span className={clsx(
                    'text-xs font-semibold px-2 py-0.5 rounded shrink-0',
                    isBuy   ? 'bg-green/10 text-green' :
                    isSell  ? 'bg-red/10 text-red' :
                    isClose ? 'bg-amber/10 text-amber' : 'bg-border text-dim',
                  )}>
                    {s.type}
                  </span>
                  <span className="text-sm font-mono font-semibold">{s.symbol}</span>
                  {s.price != null && (
                    <span className="text-xs text-dim font-mono">₹{s.price.toFixed(2)}</span>
                  )}
                  {s.pnl != null && (
                    <span className={clsx(
                      'text-xs font-mono ml-auto',
                      s.pnl >= 0 ? 'text-green' : 'text-red',
                    )}>
                      {pnlFmt(s.pnl)}
                    </span>
                  )}
                  {s.strategy && (
                    <span className="text-xs text-dim font-mono ml-auto hidden md:block">{s.strategy}</span>
                  )}
                  {s.confidence != null && (
                    <span className="text-xs text-dim font-mono">
                      {(s.confidence * 100).toFixed(0)}%
                    </span>
                  )}
                </div>
              )
            })}
          </div>
        ) : (
          <div className="px-5 py-8 text-center text-dim text-sm">No signals logged yet.</div>
        )}
      </div>
    </div>
  )
}
