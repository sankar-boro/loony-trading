import useSWR from 'swr'
import { fetcher } from '../api'
import type { PositionsResponse } from '../types'
import clsx from 'clsx'

const fmt  = (n: number) => `₹${Math.abs(n).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
const pnlFmt = (n: number) => `${n >= 0 ? '+' : '-'}${fmt(n)}`
const pct  = (n: number) => `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`

export default function Positions() {
  const { data, isLoading } = useSWR<PositionsResponse>(
    '/api/positions', fetcher, { refreshInterval: 10_000 }
  )

  const positions  = data?.positions ?? []
  const signalLog  = data?.signal_log ?? []
  const totalUnreal = positions.reduce((s, p) => s + p.unrealised_pnl, 0)

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Positions</h1>
        {isLoading && <span className="text-xs text-dim animate-pulse">Refreshing…</span>}
        {data && (
          <span className="text-xs text-dim font-mono">
            Updated {new Date(data.saved_at * 1000).toLocaleTimeString('en-IN')}
          </span>
        )}
      </div>

      {/* Open positions table */}
      <div className="bg-surface border border-border rounded-xl overflow-hidden">
        <div className="flex items-center justify-between px-5 py-3 border-b border-border">
          <span className="text-sm font-medium">Open Positions ({positions.length})</span>
          {positions.length > 0 && (
            <span className={clsx('text-sm font-mono font-medium',
              totalUnreal >= 0 ? 'text-green' : 'text-red')}>
              {pnlFmt(totalUnreal)} unrealised
            </span>
          )}
        </div>

        {positions.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-xs font-mono">
              <thead>
                <tr className="text-dim border-b border-border">
                  {['Symbol', 'Side', 'Qty', 'Entry ₹', 'CMP ₹', 'SL ₹', 'TP ₹', 'P&L ₹', 'P&L %', 'Strategy', 'Since'].map(h => (
                    <th key={h} className="text-left px-4 py-2.5 font-medium whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {positions.map((p, i) => {
                  const pnlPct = p.entry_price
                    ? p.unrealised_pnl / (p.entry_price * Math.abs(p.size)) * 100 : 0
                  const slDist = p.entry_price ? Math.abs(p.entry_price - p.stop_loss) / p.entry_price * 100 : 0
                  return (
                    <tr key={i} className="hover:bg-border/20 transition-colors">
                      <td className="px-4 py-2.5 font-semibold">{p.symbol}</td>
                      <td className={clsx('px-4 py-2.5 font-semibold',
                        p.direction === 1 ? 'text-green' : 'text-red')}>
                        {p.direction === 1 ? '▲ LONG' : '▼ SHORT'}
                      </td>
                      <td className="px-4 py-2.5">{p.size.toLocaleString()}</td>
                      <td className="px-4 py-2.5">{p.entry_price.toFixed(2)}</td>
                      <td className="px-4 py-2.5">{p.current_price.toFixed(2)}</td>
                      <td className="px-4 py-2.5 text-red">{p.stop_loss.toFixed(2)}</td>
                      <td className="px-4 py-2.5 text-green">{p.take_profit.toFixed(2)}</td>
                      <td className={clsx('px-4 py-2.5 font-semibold',
                        p.unrealised_pnl >= 0 ? 'text-green' : 'text-red')}>
                        {pnlFmt(p.unrealised_pnl)}
                      </td>
                      <td className={clsx('px-4 py-2.5',
                        pnlPct >= 0 ? 'text-green' : 'text-red')}>
                        {pct(pnlPct)}
                      </td>
                      <td className="px-4 py-2.5 text-dim">{p.strategy}</td>
                      <td className="px-4 py-2.5 text-dim">{p.entry_time}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="px-5 py-8 text-center text-dim text-sm">
            {data ? 'No open positions.' : 'Bot not running — no position data.'}
          </div>
        )}
      </div>

      {/* Signal log */}
      <div className="bg-surface border border-border rounded-xl overflow-hidden">
        <div className="px-5 py-3 border-b border-border text-sm font-medium">
          Recent Signals ({Math.min(signalLog.length, 50)})
        </div>
        {signalLog.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-xs font-mono">
              <thead>
                <tr className="text-dim border-b border-border">
                  {['Time', 'Type', 'Symbol', 'Price ₹', 'Size', 'P&L ₹', 'Strategy', 'Confidence'].map(h => (
                    <th key={h} className="text-left px-4 py-2.5 font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {[...signalLog].reverse().slice(0, 50).map((s, i) => {
                  const isBuy  = s.type === 'BUY'
                  const isSell = s.type === 'SELL'
                  const isClose = s.type === 'CLOSE'
                  return (
                    <tr key={i} className="hover:bg-border/20 transition-colors">
                      <td className="px-4 py-2 text-dim">{s.time}</td>
                      <td className={clsx('px-4 py-2 font-semibold',
                        isBuy ? 'text-green' : isSell ? 'text-red' : isClose ? 'text-amber' : 'text-dim')}>
                        {s.type}
                      </td>
                      <td className="px-4 py-2 font-semibold">{s.symbol}</td>
                      <td className="px-4 py-2">{s.price?.toFixed(2) ?? '—'}</td>
                      <td className="px-4 py-2">{s.size ?? '—'}</td>
                      <td className={clsx('px-4 py-2',
                        (s.pnl ?? 0) >= 0 ? 'text-green' : 'text-red')}>
                        {s.pnl != null ? pnlFmt(s.pnl) : '—'}
                      </td>
                      <td className="px-4 py-2 text-dim">{s.strategy ?? '—'}</td>
                      <td className="px-4 py-2 text-dim">
                        {s.confidence != null ? `${(s.confidence * 100).toFixed(0)}%` : '—'}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="px-5 py-8 text-center text-dim text-sm">No signals logged yet.</div>
        )}
      </div>
    </div>
  )
}
