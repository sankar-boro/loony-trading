import { NavLink, Outlet } from 'react-router-dom'
import useSWR from 'swr'
import { fetcher } from '../api'
import type { StatusResponse } from '../types'
import clsx from 'clsx'

const NAV = [
  { to: '/',           label: 'Dashboard',   icon: '▦' },
  { to: '/chart',      label: 'Chart',       icon: '📊' },
  { to: '/positions',  label: 'Positions',   icon: '💼' },
  { to: '/trades',     label: 'Trades',      icon: '📜' },
  { to: '/daily',      label: 'Daily P&L',   icon: '📅' },
  { to: '/strategies', label: 'Strategies',  icon: '🎯' },
  { to: '/backtest',   label: 'Backtest',    icon: '🔁' },
]

function StatusDot({ ok }: { ok: boolean }) {
  return (
    <span className={clsx(
      'inline-block w-2 h-2 rounded-full',
      ok ? 'bg-green animate-pulse' : 'bg-red'
    )} />
  )
}

export default function Layout() {
  const { data: status } = useSWR<StatusResponse>('/api/status', fetcher, { refreshInterval: 10_000 })

  return (
    <div className="flex h-screen bg-bg text-primary font-['Inter',sans-serif] overflow-hidden">
      {/* Sidebar */}
      <aside className="w-56 flex-shrink-0 bg-surface border-r border-border flex flex-col">
        {/* Logo */}
        <div className="px-5 py-4 border-b border-border">
          <div className="text-lg font-semibold tracking-tight">📈 Loony</div>
          <div className="text-xs text-dim mt-0.5">Trading Dashboard</div>
        </div>

        {/* Nav */}
        <nav className="flex-1 px-2 py-3 space-y-0.5">
          {NAV.map(({ to, label, icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) => clsx(
                'flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors',
                isActive
                  ? 'bg-blue/10 text-blue font-medium'
                  : 'text-dim hover:text-primary hover:bg-surface'
              )}
            >
              <span className="text-base w-5 text-center">{icon}</span>
              {label}
            </NavLink>
          ))}
        </nav>

        {/* Status panel */}
        <div className="px-4 py-4 border-t border-border space-y-3 text-xs">
          {/* Market */}
          <div className="flex items-center gap-2">
            <StatusDot ok={status?.market_open ?? false} />
            <span className="text-dim">
              {status?.market_open
                ? `NSE open  ·  ${status.mins_to_close}m left`
                : status
                  ? `NSE closed  ·  ${status.next_market_open}`
                  : 'NSE —'}
            </span>
          </div>
          {/* Bot */}
          <div className="flex items-center gap-2">
            <StatusDot ok={status?.bot_running ?? false} />
            <span className="text-dim">
              {status?.bot_running ? 'Bot running' : 'Bot stopped'}
            </span>
          </div>
          {/* Token */}
          <div className="flex items-center gap-2">
            <StatusDot ok={status?.token_valid ?? false} />
            <span className="text-dim">
              {status?.token_valid
                ? `Token  ·  ${status.token_age_h.toFixed(0)}h old`
                : 'No token'}
            </span>
          </div>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 h-full overflow-y-auto">
        <Outlet />
      </main>
    </div>
  )
}
