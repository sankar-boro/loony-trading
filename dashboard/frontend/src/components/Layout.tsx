import { NavLink, Outlet } from 'react-router-dom'
import useSWR from 'swr'
import { fetcher } from '../api'
import type { StatusResponse } from '../types'
import clsx from 'clsx'

const NAV = [
  { to: '/',           label: 'Dashboard',  icon: '◈' },
  { to: '/chart',      label: 'Chart',      icon: '◌' },
  { to: '/positions',  label: 'Positions',  icon: '◎' },
  { to: '/trades',     label: 'Trades',     icon: '≡' },
  { to: '/strategies', label: 'Strategies', icon: '◇' },
  { to: '/backtest',   label: 'Backtest',   icon: '▷' },
  { to: '/daily',      label: 'Daily P&L',  icon: '▤' },
  { to: '/news',       label: 'News',       icon: '⚡' },
  { to: '/signals',    label: 'Signals',    icon: '◈' },
  { to: '/copilot',    label: 'Copilot',    icon: '✦' },
  { to: '/watchlists', label: 'Watchlists', icon: '◎' },
  { to: '/alerts',     label: 'Alerts',     icon: '🔔' },
  { to: '/risk',       label: 'Portfolio Risk', icon: '⚖' },
]

function Dot({ on, pulse }: { on: boolean; pulse?: boolean }) {
  return (
    <span className={clsx(
      'inline-block w-1.5 h-1.5 rounded-full shrink-0',
      on ? 'bg-green' : 'bg-muted',
      on && pulse && 'animate-pulse',
    )} />
  )
}

export default function Layout() {
  const { data: status } = useSWR<StatusResponse>('/api/status', fetcher, { refreshInterval: 10_000 })

  const marketOpen  = status?.market_open ?? false
  const botRunning  = status?.bot_running ?? false
  const tokenOk     = status?.token_valid ?? false
  const demoMode    = status?.demo_mode ?? false

  return (
    <div className="flex h-screen bg-bg text-primary overflow-hidden select-none">

      {/* ── Sidebar ──────────────────────────────────────────────────────── */}
      <aside className="w-52 shrink-0 flex flex-col bg-surface border-r border-border">

        {/* Logo */}
        <div className="px-4 pt-5 pb-4 border-b border-border">
          <div className="flex items-center gap-2.5">
            <span className="text-blue text-xl font-bold leading-none">▲</span>
            <div>
              <div className="text-sm font-semibold text-primary tracking-wide">LOONY</div>
              <div className="text-[10px] text-dim font-mono tracking-widest">TRADING</div>
            </div>
          </div>
        </div>

        {/* Nav */}
        <nav className="flex-1 px-2 py-3 space-y-0.5 overflow-y-auto">
          {NAV.map(({ to, label, icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) => clsx(
                'flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-all duration-150',
                isActive
                  ? 'bg-blue/15 text-blue font-medium border border-blue/20'
                  : 'text-dim hover:text-primary hover:bg-white/5 border border-transparent',
              )}
            >
              <span className="font-mono text-xs w-4 text-center opacity-60">{icon}</span>
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>

        {/* Status footer */}
        <div className="px-4 py-4 border-t border-border space-y-2.5">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Dot on={marketOpen} pulse={marketOpen} />
              <span className="text-xs text-dim">Market</span>
            </div>
            <span className="text-xs font-mono text-dim truncate max-w-[80px] text-right">
              {marketOpen
                ? `${status?.mins_to_close}m left`
                : status?.next_market_open?.split('•')[0]?.trim() ?? '—'}
            </span>
          </div>

          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Dot on={botRunning} pulse={botRunning} />
              <span className="text-xs text-dim">Bot</span>
            </div>
            <span className={clsx('text-xs font-mono', botRunning ? 'text-green' : 'text-dim')}>
              {botRunning ? 'running' : 'stopped'}
            </span>
          </div>

          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Dot on={tokenOk} />
              <span className="text-xs text-dim">Token</span>
            </div>
            <span className={clsx('text-xs font-mono', tokenOk ? 'text-dim' : 'text-red')}>
              {tokenOk ? `${status?.token_age_h?.toFixed(0)}h old` : 'missing'}
            </span>
          </div>

          <div className="pt-1 border-t border-border/50">
            <span className="text-[10px] text-dim/50 font-mono">v1.1.0 · NSE</span>
          </div>
        </div>
      </aside>

      {/* ── Main content ─────────────────────────────────────────────────── */}
      <main className="flex-1 min-w-0 h-full flex flex-col overflow-hidden bg-bg">
        {demoMode && (
          <div className="shrink-0 bg-amber/15 border-b border-amber/30 px-4 py-1.5 flex items-center gap-2">
            <span className="text-amber text-xs">⚠</span>
            <span className="text-[11px] text-amber font-medium tracking-wide">DEMO DATA</span>
            <span className="text-[11px] text-dim">
              No live Upstox connection — prices, signals, and history shown are synthetic, not real market data.
            </span>
          </div>
        )}
        <div className="flex-1 min-h-0 overflow-y-auto">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
