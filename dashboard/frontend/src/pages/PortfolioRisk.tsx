import useSWR from 'swr'
import { fetcher } from '../api'
import type { PortfolioRisk } from '../types'
import clsx from 'clsx'

const inr = (n: number) => `₹${Math.abs(n).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
const pnlFmt = (n: number) => `${n >= 0 ? '+' : '-'}${inr(n)}`

function Metric({ label, value, up }: { label: string; value: string; up?: boolean }) {
  return (
    <div className="bg-surface border border-border rounded-xl px-4 py-3">
      <div className="text-[9px] text-dim uppercase tracking-wide mb-1">{label}</div>
      <div className={clsx('text-lg font-mono font-semibold',
        up === true ? 'text-green' : up === false ? 'text-red' : 'text-primary')}>
        {value}
      </div>
    </div>
  )
}

const SECTOR_COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#a855f7', '#f43f5e', '#06b6d4', '#84cc16', '#ec4899']

function correlationColor(v: number | null): string {
  if (v === null) return 'transparent'
  const abs = Math.min(1, Math.abs(v))
  if (v >= 0) return `rgba(16, 185, 129, ${abs * 0.6})`   // green tint
  return `rgba(244, 63, 94, ${abs * 0.6})`                // red tint
}

export default function PortfolioRiskPage() {
  const { data, isLoading } = useSWR<PortfolioRisk>('/api/portfolio/risk', fetcher, { refreshInterval: 15_000 })

  const sectors = Object.entries(data?.sector_exposure_pct ?? {}).sort((a, b) => b[1] - a[1])
  const maxSectorPct = Math.max(1, ...sectors.map(([, v]) => v))
  const corrSymbols = Object.keys(data?.correlation ?? {}).sort()

  return (
    <div className="flex flex-col h-full p-4 gap-3 overflow-hidden">
      <h1 className="text-base font-semibold tracking-wide shrink-0">Portfolio Risk</h1>

      {isLoading && (
        <div className="flex-1 flex items-center justify-center text-dim text-sm">Loading…</div>
      )}

      {data && (
        <div className="flex-1 flex flex-col gap-3 min-h-0 overflow-y-auto">
          {/* Warnings */}
          {data.warnings.length > 0 && (
            <div className="flex flex-col gap-1.5 shrink-0">
              {data.warnings.map((w, i) => (
                <div
                  key={i}
                  className={clsx(
                    'rounded-xl px-4 py-2.5 text-xs flex items-center gap-2 border',
                    w.severity === 'critical'
                      ? 'bg-red/10 border-red/30 text-red'
                      : 'bg-amber/10 border-amber/30 text-amber',
                  )}
                >
                  <span>{w.severity === 'critical' ? '⛔' : '⚠'}</span>
                  <span>{w.message}</span>
                </div>
              ))}
            </div>
          )}

          {/* Metrics */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2 shrink-0">
            <Metric label="Capital" value={inr(data.capital)} />
            <Metric label="Cash" value={inr(data.cash)} />
            <Metric label="Market Value" value={inr(data.market_value)} />
            <Metric label="Exposure" value={`${data.exposure_pct.toFixed(1)}%`}
                    up={data.exposure_pct <= 20} />
            <Metric label="Daily P&L" value={pnlFmt(data.daily_pnl)} up={data.daily_pnl >= 0} />
            <Metric label="Unrealized P&L" value={pnlFmt(data.unrealized_pnl)} up={data.unrealized_pnl >= 0} />
            <Metric label="Max Loss (at stops)" value={inr(data.max_loss)} up={false} />
            <Metric label="Open Positions" value={String(data.open_positions)} />
          </div>

          <div className="flex-1 grid grid-cols-1 xl:grid-cols-2 gap-3 min-h-0">
            {/* Sector exposure */}
            <div className="bg-surface border border-border rounded-xl p-4 flex flex-col overflow-hidden">
              <div className="text-xs font-medium mb-3 text-dim uppercase tracking-wide">Sector Exposure</div>
              {sectors.length === 0 ? (
                <div className="flex-1 flex items-center justify-center text-dim text-xs">
                  No open positions
                </div>
              ) : (
                <div className="flex flex-col gap-2.5 overflow-y-auto">
                  {sectors.map(([sector, pct], i) => (
                    <div key={sector} className="flex flex-col gap-1">
                      <div className="flex items-center justify-between text-xs">
                        <span className="text-primary">{sector}</span>
                        <span className="font-mono text-dim">{pct.toFixed(1)}%</span>
                      </div>
                      <div className="h-2 rounded-full bg-white/5 overflow-hidden">
                        <div
                          className="h-full rounded-full transition-all"
                          style={{
                            width: `${(pct / maxSectorPct) * 100}%`,
                            backgroundColor: SECTOR_COLORS[i % SECTOR_COLORS.length],
                          }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Correlation matrix */}
            <div className="bg-surface border border-border rounded-xl p-4 flex flex-col overflow-hidden">
              <div className="text-xs font-medium mb-3 text-dim uppercase tracking-wide">
                Position Correlation
              </div>
              {corrSymbols.length < 2 ? (
                <div className="flex-1 flex items-center justify-center text-dim text-xs text-center px-4">
                  Need 2+ open positions with price history to compute correlation
                </div>
              ) : (
                <div className="overflow-auto">
                  <table className="text-[10px] font-mono border-collapse">
                    <thead>
                      <tr>
                        <th className="p-1"></th>
                        {corrSymbols.map(s => (
                          <th key={s} className="p-1 text-dim font-normal whitespace-nowrap">{s}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {corrSymbols.map(a => (
                        <tr key={a}>
                          <td className="p-1 text-dim whitespace-nowrap pr-2">{a}</td>
                          {corrSymbols.map(b => {
                            const v = data.correlation[a]?.[b] ?? null
                            return (
                              <td
                                key={b}
                                className="w-10 h-8 text-center align-middle"
                                style={{ backgroundColor: correlationColor(v) }}
                                title={v !== null ? `${a} vs ${b}: ${v.toFixed(2)}` : 'n/a'}
                              >
                                {v !== null ? v.toFixed(2) : '—'}
                              </td>
                            )
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
