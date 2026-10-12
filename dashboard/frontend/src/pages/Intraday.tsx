import { useState } from 'react'
import useSWR from 'swr'
import { api, fetcher } from '../api'
import type { IntradayScanResponse, AlertEvaluateResponse, SchedulerStatus } from '../types'
import clsx from 'clsx'

// "30m" not "15m" — Upstox returns HTTP 400 for 5m/15m on this account
// (docs/appendix/intraday-audit.md §5); 30m/1h are the verified-working options.
const TIMEFRAMES = ['30m', '1h'] as const

const DIR_CLASS: Record<string, string> = {
  bullish: 'bg-green/15 text-green', bearish: 'bg-red/15 text-red',
  watch: 'bg-amber-500/15 text-amber-400', no_signal: 'bg-white/5 text-dim',
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-[11px] text-dim uppercase tracking-wide">{label}</label>
      {children}
    </div>
  )
}

const inputCls = "bg-bg border border-border rounded-lg px-3 py-1.5 text-sm text-primary placeholder:text-dim focus:outline-none focus:border-blue"

export default function Intraday() {
  return (
    <div className="flex flex-col h-full p-4 gap-3 overflow-y-auto">
      <div>
        <h1 className="text-lg font-semibold tracking-wide">Intraday Lab</h1>
        <p className="text-sm text-dim mt-1">
          UI-triggered versions of the terminal commands used to verify the intraday fixes —
          same functions, same persisted data, just reachable from a button instead of a shell.
        </p>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
        <SignalScanCard />
        <AlertEvalCard />
      </div>

      <SchedulerStatusCard />
    </div>
  )
}

function SignalScanCard() {
  const [symbols, setSymbols] = useState('')
  const [timeframe, setTimeframe] = useState<typeof TIMEFRAMES[number]>('30m')
  const [lookbackDays, setLookbackDays] = useState(5)
  const [limit, setLimit] = useState(5)
  const [status, setStatus] = useState<'idle' | 'running' | 'done' | 'error'>('idle')
  const [result, setResult] = useState<IntradayScanResponse | null>(null)
  const [errMsg, setErrMsg] = useState('')

  const run = async () => {
    setStatus('running'); setResult(null); setErrMsg('')
    try {
      const symbolList = symbols.split(',').map(s => s.trim().toUpperCase()).filter(Boolean)
      const res = await api.intradayScan({
        symbols: symbolList,
        limit: symbolList.length ? undefined : limit,
        lookback_days: lookbackDays,
        timeframe,
      })
      setResult(res)
      setStatus('done')
    } catch (e: any) {
      setStatus('error'); setErrMsg(e.message ?? 'Scan failed')
    }
  }

  return (
    <div className="bg-surface border border-border rounded-xl p-4 flex flex-col gap-3">
      <div className="text-sm font-medium text-dim uppercase tracking-wide">
        Intraday Signal Scan
      </div>
      <p className="text-[13px] text-dim -mt-1">
        Equivalent to <code className="text-primary">python3 scripts/run_signal_engine.py --timeframe {timeframe}</code>.
        Scores real bars through the composite engine and persists Signal rows tagged with this
        timeframe — the daily Signals page is unaffected.
      </p>

      <div className="grid grid-cols-2 gap-2.5">
        <Field label="Symbols (blank = universe)">
          <input className={inputCls} value={symbols} onChange={e => setSymbols(e.target.value)}
                 placeholder="RELIANCE, TCS…" />
        </Field>
        <Field label="Timeframe">
          <select className={inputCls} value={timeframe} onChange={e => setTimeframe(e.target.value as any)}>
            {TIMEFRAMES.map(tf => <option key={tf} value={tf}>{tf}</option>)}
          </select>
        </Field>
        <Field label="Lookback days">
          <input type="number" className={inputCls} value={lookbackDays} min={1} max={60}
                 onChange={e => setLookbackDays(Number(e.target.value))} />
        </Field>
        <Field label="Limit (if no symbols)">
          <input type="number" className={inputCls} value={limit} min={1} max={20}
                 onChange={e => setLimit(Number(e.target.value))} />
        </Field>
      </div>

      <button
        onClick={run} disabled={status === 'running'}
        className="self-start px-4 py-1.5 rounded-lg bg-blue text-white text-sm font-medium hover:bg-blue/90 disabled:opacity-50 transition-colors flex items-center gap-2"
      >
        {status === 'running' && <span className="w-3 h-3 rounded-full border-2 border-white/30 border-t-white animate-spin" />}
        {status === 'running' ? 'Scanning…' : '▷ Run Scan'}
      </button>

      {status === 'error' && (
        <div className="bg-red/10 border border-red/30 rounded-lg px-3 py-2 text-[13px] text-red">{errMsg}</div>
      )}

      {result && (
        <div className="flex flex-col gap-2">
          <div className="text-[13px] text-dim">
            {result.scored} scored, {result.skipped} skipped, {result.universe} in universe ({result.timeframe})
          </div>
          {result.results.length > 0 && (
            <table className="w-full text-[13px] font-mono">
              <thead>
                <tr className="text-dim text-left">
                  <th className="font-normal pb-1">Symbol</th>
                  <th className="font-normal pb-1">Direction</th>
                  <th className="font-normal pb-1">Score</th>
                  <th className="font-normal pb-1">Confidence</th>
                </tr>
              </thead>
              <tbody>
                {result.results.map(r => (
                  <tr key={r.symbol} className="border-t border-border/50">
                    <td className="py-1 font-semibold">{r.symbol}</td>
                    <td className="py-1">
                      <span className={clsx('px-1.5 py-0.5 rounded text-[11px] font-bold', DIR_CLASS[r.direction])}>
                        {r.direction}
                      </span>
                    </td>
                    <td className="py-1">{r.score.toFixed(1)}</td>
                    <td className="py-1">{r.confidence.toFixed(0)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {result.errors.length > 0 && (
            <div className="flex flex-col gap-1">
              {result.errors.map((e, i) => (
                <div key={i} className="text-[12px] text-amber-400">{e.symbol}: {e.error}</div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function AlertEvalCard() {
  const [timeframe, setTimeframe] = useState<typeof TIMEFRAMES[number]>('30m')
  const [status, setStatus] = useState<'idle' | 'running' | 'done' | 'error'>('idle')
  const [result, setResult] = useState<AlertEvaluateResponse | null>(null)
  const [errMsg, setErrMsg] = useState('')

  const run = async () => {
    setStatus('running'); setResult(null); setErrMsg('')
    try {
      const res = await api.evaluateAlerts(timeframe)
      setResult(res)
      setStatus('done')
    } catch (e: any) {
      setStatus('error'); setErrMsg(e.message ?? 'Evaluation failed')
    }
  }

  return (
    <div className="bg-surface border border-border rounded-xl p-4 flex flex-col gap-3">
      <div className="text-sm font-medium text-dim uppercase tracking-wide">
        Intraday Alert Evaluation
      </div>
      <p className="text-[13px] text-dim -mt-1">
        Evaluates every active alert against the latest signal of the chosen timeframe instead
        of the default daily one. Run a scan above first, or nothing will match.
      </p>

      <Field label="Timeframe">
        <select className={clsx(inputCls, 'w-32')} value={timeframe} onChange={e => setTimeframe(e.target.value as any)}>
          {TIMEFRAMES.map(tf => <option key={tf} value={tf}>{tf}</option>)}
        </select>
      </Field>

      <button
        onClick={run} disabled={status === 'running'}
        className="self-start px-4 py-1.5 rounded-lg bg-blue/15 text-blue text-sm font-medium hover:bg-blue/25 disabled:opacity-50 transition-colors"
      >
        {status === 'running' ? 'Evaluating…' : '🔔 Evaluate Now'}
      </button>

      {status === 'error' && (
        <div className="bg-red/10 border border-red/30 rounded-lg px-3 py-2 text-[13px] text-red">{errMsg}</div>
      )}

      {result && (
        <div className="flex flex-col gap-1.5">
          <div className="text-[13px] text-dim">
            {result.alerts_checked} alert(s) checked at {result.timeframe} · {result.triggers.length} trigger(s)
          </div>
          {result.triggers.map((t, i) => (
            <div key={i} className="flex items-center justify-between text-[13px] bg-white/3 rounded-lg px-3 py-1.5">
              <span className="font-mono text-primary">{t.symbol}</span>
              <span className="text-dim">{t.alert_name}</span>
              <span className="text-dim font-mono">{JSON.stringify(t.matched_values)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function SchedulerStatusCard() {
  const { data, isLoading } = useSWR<SchedulerStatus>('/api/scheduler/status', fetcher, { refreshInterval: 15_000 })

  const jobOrder = [
    'news_ingest', 'signal_engine', 'alert_evaluation', 'historical_backfill',
    'intraday_signal_engine', 'intraday_alert_evaluation',
  ]
  const intradayJobs = new Set(['intraday_signal_engine', 'intraday_alert_evaluation'])

  return (
    <div className="bg-surface border border-border rounded-xl p-4 flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <div className="text-sm font-medium text-dim uppercase tracking-wide">Scheduler Status</div>
        {data && (
          <span className={clsx('w-1.5 h-1.5 rounded-full', data.running ? 'bg-green animate-pulse' : 'bg-dim')} />
        )}
        {data && <span className="text-[12px] text-dim">{data.running ? 'running' : 'disabled'}</span>}
      </div>

      {!data?.running && !isLoading && (
        <p className="text-[13px] text-dim">
          The scheduler is off by default (<code className="text-primary">scheduler.enabled: false</code>).
          Enable <code className="text-primary">scheduler.intraday_enabled</code> in
          <code className="text-primary"> config/settings.yaml</code> to run the intraday scan/evaluate
          jobs above automatically instead of by hand.
        </p>
      )}

      {data?.running && (
        <table className="w-full text-[13px] font-mono">
          <thead>
            <tr className="text-dim text-left">
              <th className="font-normal pb-1">Job</th>
              <th className="font-normal pb-1">Next Run</th>
              <th className="font-normal pb-1">Last Run</th>
            </tr>
          </thead>
          <tbody>
            {jobOrder.filter(id => data.next_runs[id] !== undefined || data.last_runs[id]).map(id => {
              const last = data.last_runs[id]
              return (
                <tr key={id} className="border-t border-border/50">
                  <td className="py-1.5">
                    {id}
                    {intradayJobs.has(id) && (
                      <span className="ml-1.5 px-1 py-0.5 rounded text-[10px] bg-blue/15 text-blue">intraday</span>
                    )}
                  </td>
                  <td className="py-1.5 text-dim">
                    {data.next_runs[id] ? new Date(data.next_runs[id]!).toLocaleTimeString('en-IN') : '—'}
                  </td>
                  <td className="py-1.5">
                    {last ? (
                      <span className={last.ok ? 'text-green' : 'text-red'}>
                        {last.ok ? '✓' : '✗'} {new Date(last.started_at).toLocaleTimeString('en-IN')}
                      </span>
                    ) : <span className="text-dim">never</span>}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </div>
  )
}
