import useSWR from 'swr'
import { fetcher } from '../api'
import type { PortfolioRisk, PortfolioAnalytics } from '../types'
import clsx from 'clsx'

const inr = (n: number) => `₹${Math.abs(n).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
const pnlFmt = (n: number) => `${n >= 0 ? '+' : '-'}${inr(n)}`

function Metric({ label, value, up }: { label: string; value: string; up?: boolean }) {
  return (
    <div className="bg-surface border border-border rounded-xl px-4 py-3">
      <div className="text-[11px] text-dim uppercase tracking-wide mb-1">{label}</div>
      <div className={clsx('text-xl font-mono font-semibold',
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

const FACTOR_LABEL: Record<string, string> = {
  market: 'Nifty 50', banking: 'Bank Nifty', it: 'Nifty IT', fmcg: 'Nifty FMCG',
  auto: 'Nifty Auto', midcap: 'Midcap 150',
}

function Analytics() {
  const { data: a, isLoading, error } = useSWR<PortfolioAnalytics>('/api/portfolio/analytics', fetcher,
                                                                   { refreshInterval: 300_000 })
  const card = 'bg-surface border border-border rounded-xl'
  const title = 'px-4 py-2.5 border-b border-border text-sm font-medium text-dim uppercase tracking-wide'
  if (isLoading) return <div className={clsx(card, 'p-4 text-sm text-dim animate-pulse')}>Computing beta, factors and stress tests…</div>
  if (error || !a) return <div className={clsx(card, 'p-4 text-sm text-dim')}>Analytics unavailable (needs daily bars from Upstox or the cache).</div>
  if (!a.positions) return null
  return (
    <div className="grid grid-cols-1 xl:grid-cols-3 gap-3 shrink-0">
      {/* Beta */}
      <div className={card}>
        <div className={title}>Market beta</div>
        <div className="p-4 space-y-3">
          <div className="flex items-baseline gap-3">
            <span className="text-2xl font-mono font-semibold">{a.beta?.portfolio.toFixed(2)}</span>
            <span className="text-sm text-dim">portfolio β vs Nifty · {inr(a.beta?.beta_exposure ?? 0)} beta exposure</span>
          </div>
          {a.beta?.hedge ? (
            <div className="text-sm rounded-lg border border-amber/30 bg-amber/10 text-amber px-3 py-2">
              Hedge: {a.beta.hedge.direction.toUpperCase()} {a.beta.hedge.lots} lot(s) of {a.beta.hedge.instrument} ({inr(a.beta.hedge.notional)})
            </div>
          ) : a.beta?.hedge_note && <div className="text-[12px] text-dim">{a.beta.hedge_note}</div>}
          <table className="w-full text-sm font-mono">
            <tbody className="divide-y divide-border/50">
              {Object.entries(a.beta?.per_symbol ?? {}).map(([s, b]) => (
                <tr key={s}>
                  <td className="py-1.5">{s}</td>
                  <td className="py-1.5 text-right">{b.beta.toFixed(2)}</td>
                  <td className="py-1.5 text-right text-dim text-[12px]">R² {b.r_squared.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Factors */}
      <div className={card}>
        <div className={title}>Factor exposures</div>
        {a.factors ? (
          <div className="p-4 space-y-2">
            <div className="text-[12px] text-dim">
              Current holdings over the last {a.factors.n_obs} days: R² {a.factors.r_squared.toFixed(2)},
              alpha {a.factors.alpha_annual_pct >= 0 ? '+' : ''}{a.factors.alpha_annual_pct.toFixed(1)}%/yr,
              residual vol {a.factors.residual_vol_pct.toFixed(1)}%
            </div>
            {Object.entries(a.factors.loadings).map(([f, b]) => (
              <div key={f} className="flex items-center gap-3 text-sm">
                <span className="w-24 text-dim">{FACTOR_LABEL[f] ?? f}</span>
                <div className="flex-1 h-2 bg-border rounded-full relative overflow-hidden">
                  <div className={clsx('absolute inset-y-0', b >= 0 ? 'bg-blue/70 left-1/2' : 'bg-red/70 right-1/2')}
                       style={{ width: `${Math.min(Math.abs(b), 1.5) / 1.5 * 50}%` }} />
                  <div className="absolute inset-y-0 left-1/2 w-px bg-dim/50" />
                </div>
                <span className="w-12 text-right font-mono" title={`t = ${a.factors!.t_stats[f]?.toFixed(1)}`}>{b.toFixed(2)}</span>
              </div>
            ))}
            {a.factors.hedge_suggestion && (
              <div className="text-[12px] text-amber pt-1">Sector concentration — consider {a.factors.hedge_suggestion}</div>
            )}
          </div>
        ) : <div className="p-4 text-sm text-dim">Not enough history.</div>}
      </div>

      {/* Stress */}
      <div className={card}>
        <div className={title}>Crisis stress test</div>
        <div className="p-4">
          <div className="text-[12px] text-dim mb-2">
            Past Nifty crises replayed on this book (β {a.stress?.capital_beta.toFixed(2)} of capital).
            Fails if drawdown exceeds 20%.
          </div>
          <table className="w-full text-sm font-mono">
            <thead><tr className="text-[11px] uppercase text-dim">
              <th className="text-left font-medium py-1">Scenario</th>
              <th className="text-right font-medium py-1">Return</th>
              <th className="text-right font-medium py-1">Max DD</th>
              <th className="text-right font-medium py-1"></th>
            </tr></thead>
            <tbody className="divide-y divide-border/50">
              {a.stress?.scenarios.map(s => (
                <tr key={s.key} className={clsx(a.stress?.worst === s.key && 'text-red')}>
                  <td className="py-1.5 font-sans">{s.name}</td>
                  <td className="py-1.5 text-right">{s.return_pct.toFixed(1)}%</td>
                  <td className="py-1.5 text-right">{s.max_drawdown_pct.toFixed(1)}%</td>
                  <td className="py-1.5 text-right">{s.survived ? <span className="text-green">✓</span> : <span className="text-red">✗</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

export default function PortfolioRiskPage() {
  const { data, isLoading } = useSWR<PortfolioRisk>('/api/portfolio/risk', fetcher, { refreshInterval: 15_000 })

  const sectors = Object.entries(data?.sector_exposure_pct ?? {}).sort((a, b) => b[1] - a[1])
  const maxSectorPct = Math.max(1, ...sectors.map(([, v]) => v))
  const corrSymbols = Object.keys(data?.correlation ?? {}).sort()

  return (
    <div className="flex flex-col h-full p-4 gap-3 overflow-hidden">
      <h1 className="text-lg font-semibold tracking-wide shrink-0">Portfolio Risk</h1>

      {isLoading && (
        <div className="flex-1 flex items-center justify-center text-dim text-base">Loading…</div>
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
                    'rounded-xl px-4 py-2.5 text-sm flex items-center gap-2 border',
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
              <div className="text-sm font-medium mb-3 text-dim uppercase tracking-wide">Sector Exposure</div>
              {sectors.length === 0 ? (
                <div className="flex-1 flex items-center justify-center text-dim text-sm">
                  No open positions
                </div>
              ) : (
                <div className="flex flex-col gap-2.5 overflow-y-auto">
                  {sectors.map(([sector, pct], i) => (
                    <div key={sector} className="flex flex-col gap-1">
                      <div className="flex items-center justify-between text-sm">
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
              <div className="text-sm font-medium mb-3 text-dim uppercase tracking-wide">
                Position Correlation
              </div>
              {corrSymbols.length < 2 ? (
                <div className="flex-1 flex items-center justify-center text-dim text-sm text-center px-4">
                  Need 2+ open positions with price history to compute correlation
                </div>
              ) : (
                <div className="overflow-auto">
                  <table className="text-[12px] font-mono border-collapse">
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
          {data.open_positions > 0 && <Analytics />}
        </div>
      )}
    </div>
  )
}
