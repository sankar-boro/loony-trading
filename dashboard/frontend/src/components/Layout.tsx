import { useEffect, useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import useSWR from 'swr'
import { api, fetcher, AUTH_EVENT } from '../api'
import type { StatusResponse } from '../types'
import clsx from 'clsx'

const NAV = [
  { to: '/',           label: 'Dashboard',  icon: '◈' },
  { to: '/desk',       label: 'Intraday Desk', icon: '◷' },
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
  { to: '/intraday',   label: 'Intraday Lab', icon: '⏱' },
  { to: '/docs',       label: 'Docs',       icon: '¶' },
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

interface AuthStatus { password_set: boolean; local: boolean; authenticated: boolean }

function Login({ auth, onDone }: { auth: AuthStatus; onDone: () => void }) {
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true); setError('')
    try { await api.login(password); onDone() }
    catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy(false) }
  }
  return (
    <div className="h-screen flex items-center justify-center bg-bg text-primary">
      <div className="w-80 bg-surface border border-border rounded-xl p-6 space-y-4">
        <div className="flex items-center gap-2.5">
          <span className="text-blue text-2xl font-bold leading-none">▲</span>
          <span className="text-base font-semibold tracking-wide">LOONY TRADING</span>
        </div>
        {auth.password_set ? (
          <form onSubmit={submit} className="space-y-3">
            <input type="password" autoFocus value={password} onChange={e => setPassword(e.target.value)}
                   placeholder="Dashboard password"
                   className="w-full bg-bg border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue" />
            {error && <div className="text-sm text-red">{error}</div>}
            <button disabled={busy || !password}
                    className="w-full bg-blue text-white rounded-lg py-2 text-sm font-medium disabled:opacity-40">
              {busy ? 'Signing in…' : 'Sign in'}
            </button>
          </form>
        ) : (
          <div className="text-sm text-dim space-y-2">
            <p>This dashboard only answers the machine it runs on.</p>
            <p>To use it from here, set <code className="text-blue">DASHBOARD_PASSWORD</code> in the
               server's <code className="text-blue">.env</code> and restart it.</p>
          </div>
        )}
      </div>
    </div>
  )
}

export default function Layout() {
  const { data: auth, mutate: recheck } = useSWR<AuthStatus>('/api/auth/status', fetcher, { refreshInterval: 60_000 })
  useEffect(() => {
    const onAuth = () => { recheck() }
    window.addEventListener(AUTH_EVENT, onAuth)
    return () => window.removeEventListener(AUTH_EVENT, onAuth)
  }, [recheck])
  if (auth && !auth.authenticated) return <Login auth={auth} onDone={() => recheck()} />
  return <Shell showLogout={!!auth?.password_set} onLogout={async () => { await api.logout(); recheck() }} />
}

function Shell({ showLogout, onLogout }: { showLogout: boolean; onLogout: () => void }) {
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
            <span className="text-blue text-2xl font-bold leading-none">▲</span>
            <div>
              <div className="text-base font-semibold text-primary tracking-wide">LOONY</div>
              <div className="text-[12px] text-dim font-mono tracking-widest">TRADING</div>
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
                'flex items-center gap-3 px-3 py-2 rounded-lg text-base transition-all duration-150',
                isActive
                  ? 'bg-blue/15 text-blue font-medium border border-blue/20'
                  : 'text-dim hover:text-primary hover:bg-white/5 border border-transparent',
              )}
            >
              <span className="font-mono text-sm w-4 text-center opacity-60">{icon}</span>
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>

        {/* Status footer */}
        <div className="px-4 py-4 border-t border-border space-y-2.5">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Dot on={marketOpen} pulse={marketOpen} />
              <span className="text-sm text-dim">Market</span>
            </div>
            <span className="text-sm font-mono text-dim truncate max-w-[80px] text-right">
              {marketOpen
                ? `${status?.mins_to_close}m left`
                : status?.next_market_open?.split('•')[0]?.trim() ?? '—'}
            </span>
          </div>

          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Dot on={botRunning} pulse={botRunning} />
              <span className="text-sm text-dim">Bot</span>
            </div>
            <span className={clsx('text-sm font-mono', botRunning ? 'text-green' : 'text-dim')}>
              {botRunning ? 'running' : 'stopped'}
            </span>
          </div>

          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Dot on={tokenOk} />
              <span className="text-sm text-dim">Token</span>
            </div>
            <span className={clsx('text-sm font-mono', tokenOk ? 'text-dim' : 'text-red')}>
              {tokenOk ? `${status?.token_age_h?.toFixed(0)}h old` : 'missing'}
            </span>
          </div>

          <div className="pt-1 border-t border-border/50 flex items-center justify-between">
            <span className="text-[12px] text-dim/50 font-mono">v1.1.0 · NSE</span>
            {showLogout && (
              <button onClick={onLogout} className="text-[12px] text-dim hover:text-primary">Sign out</button>
            )}
          </div>
        </div>
      </aside>

      {/* ── Main content ─────────────────────────────────────────────────── */}
      <main className="flex-1 min-w-0 h-full flex flex-col overflow-hidden bg-bg">
        {demoMode && (
          <div className="shrink-0 bg-amber/15 border-b border-amber/30 px-4 py-1.5 flex items-center gap-2">
            <span className="text-amber text-sm">⚠</span>
            <span className="text-[13px] text-amber font-medium tracking-wide">DEMO DATA</span>
            <span className="text-[13px] text-dim">
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
