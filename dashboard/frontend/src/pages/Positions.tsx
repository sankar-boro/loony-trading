import useSWR from 'swr'
import { fetcher } from '../api'
import type { PositionsResponse } from '../types'
import clsx from 'clsx'

const inr    = (n: number) => `₹${Math.abs(n).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
const pnlFmt = (n: number) => `${n >= 0 ? '+' : '-'}${inr(n)}`
const pct    = (n: number) => `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`
const pr     = (n: number) => n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

// ── Position row (table row style) ────────────────────────────────────────────

function PositionRow({ p }: { p: PositionsResponse['positions'][0] }) {
  const pnlPct  = p.entry_price ? (p.unrealised_pnl / (p.entry_price * Math.abs(p.size))) * 100 : 0
  const range   = Math.abs(p.take_profit - p.stop_loss)
  const progress = range > 0 ? Math.min(1, Math.max(0, (p.current_price - p.stop_loss) / range)) : 0.5
  const isLong  = p.direction === 1
  const inProfit = p.unrealised_pnl >= 0

  return (
    <div className="grid grid-cols-[1fr_auto] gap-4 px-4 py-3 hover:bg-white/3 border-b border-border/50 last:border-0 transition-colors">
      {/* Left: symbol + details */}
      <div className="space-y-2 min-w-0">
        {/* Header row */}
        <div className="flex items-center gap-2.5">
          <span className="font-mono font-semibold text-sm">{p.symbol}</span>
          <span className={clsx(
            'text-[10px] font-bold px-1.5 py-0.5 rounded',
            isLong ? 'bg-green/15 text-green' : 'bg-red/15 text-red',
          )}>
            {isLong ? '▲ LONG' : '▼ SHORT'}
          </span>
          <span className="text-[10px] bg-blue/10 text-blue px-1.5 py-0.5 rounded font-mono">{p.strategy}</span>
          <span className="text-[10px] text-dim ml-auto">{p.entry_time}</span>
        </div>

        {/* Metrics grid */}
        <div className="grid grid-cols-5 gap-2 text-xs font-mono">
          <div>
            <div className="text-dim text-[9px] uppercase mb-0.5">Qty</div>
            <div>{Math.round(p.size)}</div>
          </div>
          <div>
            <div className="text-dim text-[9px] uppercase mb-0.5">Entry</div>
            <div>₹{pr(p.entry_price)}</div>
          </div>
          <div>
            <div className="text-dim text-[9px] uppercase mb-0.5">CMP</div>
            <div className={p.current_price >= p.entry_price ? 'text-green' : 'text-red'}>
              ₹{pr(p.current_price)}
            </div>
          </div>
          <div>
            <div className="text-dim text-[9px] uppercase mb-0.5">Stop</div>
            <div className="text-red">₹{pr(p.stop_loss)}</div>
          </div>
          <div>
            <div className="text-dim text-[9px] uppercase mb-0.5">Target</div>
            <div className="text-green">₹{pr(p.take_profit)}</div>
          </div>
        </div>

        {/* Progress bar SL→Price→TP */}
        <div>
          <div className="h-1.5 rounded-full bg-border overflow-hidden">
            <div
              className={clsx('h-full rounded-full transition-all', inProfit ? 'bg-green' : 'bg-red')}
              style={{ width: `${progress * 100}%`, opacity: 0.7 }}
            />
          </div>
          <div className="flex justify-between text-[9px] text-dim mt-0.5 font-mono">
            <span>SL {pr(p.stop_loss)}</span>
            <span>TP {pr(p.take_profit)}</span>
          </div>
        </div>
      </div>

      {/* Right: P&L */}
      <div className="flex flex-col items-end justify-center shrink-0">
        <div className={clsx('text-lg font-mono font-bold', inProfit ? 'text-green' : 'text-red')}>
          {pnlFmt(p.unrealised_pnl)}
        </div>
        <div className={clsx('text-xs font-mono', inProfit ? 'text-green/70' : 'text-red/70')}>
          {pct(pnlPct)}
        </div>
      </div>
    </div>
  )
}

// ── Main ──────────────────────────────────────────────────────────────────────

export default function Positions() {
  const { data, isLoading } = useSWR<PositionsResponse>('/api/positions', fetcher, { refreshInterval: 10_000 })

  const positions   = data?.positions ?? []
  const signalLog   = data?.signal_log ?? []
  const capital     = data?.initial_capital ?? 500_000
  const cash        = data?.cash ?? capital
  const deployed    = capital > 0 ? ((capital - cash) / capital) * 100 : 0
  const totalUnreal = positions.reduce((s, p) => s + p.unrealised_pnl, 0)

  return (
    <div className="flex flex-col h-full p-4 gap-3 overflow-hidden">

      {/* Page header */}
      <div className="flex items-center justify-between shrink-0">
        <h1 className="text-base font-semibold tracking-wide">Positions</h1>
        <div className="flex items-center gap-3">
          {isLoading && <span className="text-xs text-dim animate-pulse">Refreshing…</span>}
          {data && (
            <span className="text-xs text-dim font-mono">
              {new Date(data.saved_at * 1000).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}
            </span>
          )}
        </div>
      </div>

      {/* Exposure bar */}
      <div className="bg-surface border border-border rounded-xl px-4 py-3 shrink-0">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs font-medium">Portfolio Exposure</span>
          <div className="flex items-center gap-4 text-xs font-mono">
            <span><span className="text-dim">Deployed </span>
              <span className="text-amber">{deployed.toFixed(1)}%</span></span>
            <span><span className="text-dim">Cash </span>
              <span>{inr(cash)}</span></span>
            {positions.length > 0 && (
              <span><span className="text-dim">Unrealised </span>
                <span className={totalUnreal >= 0 ? 'text-green' : 'text-red'}>{pnlFmt(totalUnreal)}</span>
              </span>
            )}
          </div>
        </div>
        <div className="h-2 rounded-full bg-border overflow-hidden">
          <div
            className="h-full rounded-full bg-amber/70 transition-all"
            style={{ width: `${Math.min(100, deployed)}%` }}
          />
        </div>
        <div className="flex justify-between text-[9px] text-dim mt-1 font-mono">
          <span>0%</span>
          <span>{positions.length} open position{positions.length !== 1 ? 's' : ''}</span>
          <span>100%</span>
        </div>
      </div>

      {/* Bottom: positions list (left) + signal log (right) */}
      <div className="flex-1 grid grid-cols-1 xl:grid-cols-[1fr_360px] gap-3 min-h-0 overflow-hidden">

        {/* Positions */}
        <div className="bg-surface border border-border rounded-xl flex flex-col min-h-0 overflow-hidden">
          <div className="px-4 py-3 border-b border-border flex items-center justify-between shrink-0">
            <span className="text-sm font-medium">Open Positions</span>
            {positions.length > 0 && (
              <span className={clsx('text-sm font-mono font-medium', totalUnreal >= 0 ? 'text-green' : 'text-red')}>
                {pnlFmt(totalUnreal)} unrealised
              </span>
            )}
          </div>
          <div className="flex-1 overflow-y-auto min-h-0">
            {positions.length > 0 ? (
              positions.map((p, i) => <PositionRow key={i} p={p} />)
            ) : (
              <div className="flex flex-col items-center justify-center h-full gap-2 text-dim">
                <span className="text-2xl opacity-30">◎</span>
                <span className="text-sm">{data ? 'No open positions' : 'Bot not running'}</span>
                {!data && (
                  <code className="text-xs text-blue mt-1">python scripts/paper_trade.py</code>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Signal log */}
        <div className="bg-surface border border-border rounded-xl flex flex-col min-h-0 overflow-hidden">
          <div className="px-4 py-3 border-b border-border flex items-center justify-between shrink-0">
            <span className="text-sm font-medium">Signal Log</span>
            <span className="text-xs text-dim">{Math.min(signalLog.length, 100)} events</span>
          </div>
          <div className="flex-1 overflow-y-auto min-h-0 divide-y divide-border/50">
            {signalLog.length > 0 ? (
              [...signalLog].reverse().slice(0, 100).map((s, i) => {
                const isBuy   = s.type === 'BUY'
                const isSell  = s.type === 'SELL'
                const isClose = s.type === 'CLOSE'
                return (
                  <div key={i} className="px-4 py-2 flex items-center gap-2.5 hover:bg-white/3 transition-colors">
                    <span className="text-[9px] text-dim font-mono w-14 shrink-0">{s.time}</span>
                    <span className={clsx(
                      'text-[9px] font-bold px-1.5 py-0.5 rounded shrink-0 w-10 text-center',
                      isBuy   ? 'bg-green/15 text-green'  :
                      isSell  ? 'bg-red/15 text-red'    :
                      isClose ? 'bg-amber/15 text-amber' : 'bg-border text-dim',
                    )}>{s.type}</span>
                    <span className="text-xs font-mono font-medium flex-1 min-w-0 truncate">{s.symbol}</span>
                    {s.price != null && (
                      <span className="text-[10px] text-dim font-mono shrink-0">₹{s.price.toFixed(0)}</span>
                    )}
                    {s.pnl != null && (
                      <span className={clsx('text-xs font-mono font-medium shrink-0', s.pnl >= 0 ? 'text-green' : 'text-red')}>
                        {pnlFmt(s.pnl)}
                      </span>
                    )}
                  </div>
                )
              })
            ) : (
              <div className="flex items-center justify-center h-full text-xs text-dim">
                No signals logged yet
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
