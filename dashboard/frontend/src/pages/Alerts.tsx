import { useState } from 'react'
import useSWR from 'swr'
import { api, fetcher } from '../api'
import type { AlertDTO, AlertTriggerDTO } from '../types'
import clsx from 'clsx'

const FIELDS = [
  'score', 'confidence', 'catalyst_score', 'technical_score', 'momentum_score',
  'volume_score', 'historical_score', 'regime_score', 'risk_score',
]
const OPERATORS: { value: string; label: string }[] = [
  { value: 'gt', label: '>' }, { value: 'gte', label: '≥' },
  { value: 'lt', label: '<' }, { value: 'lte', label: '≤' }, { value: 'eq', label: '=' },
]

interface ConditionRow { field: string; op: string; value: string }

function TriggerHistory({ alertId }: { alertId: number }) {
  const { data } = useSWR<AlertTriggerDTO[]>(`/api/alerts/${alertId}/triggers`, fetcher)
  const triggers = data ?? []
  if (triggers.length === 0) {
    return <div className="text-[11px] text-dim px-3 py-2">No triggers yet.</div>
  }
  return (
    <div className="flex flex-col gap-1 px-3 py-2">
      {triggers.slice(0, 10).map(t => (
        <div key={t.id} className="flex items-center justify-between text-[11px]">
          <span className="font-mono text-primary">{t.symbol}</span>
          <span className="text-dim font-mono">{JSON.stringify(t.matched_values)}</span>
          <span className="text-dim">{new Date(t.created_at).toLocaleTimeString('en-IN')}</span>
        </div>
      ))}
    </div>
  )
}

export default function Alerts() {
  const { data: alerts, mutate } = useSWR<AlertDTO[]>('/api/alerts', fetcher, { refreshInterval: 30_000 })
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [evaluating, setEvaluating] = useState(false)

  const [name, setName] = useState('')
  const [symbol, setSymbol] = useState('')
  const [rows, setRows] = useState<ConditionRow[]>([{ field: 'score', op: 'gt', value: '80' }])
  const [formError, setFormError] = useState('')

  const addRow = () => setRows(r => [...r, { field: 'score', op: 'gt', value: '' }])
  const updateRow = (i: number, patch: Partial<ConditionRow>) =>
    setRows(r => r.map((row, idx) => idx === i ? { ...row, ...patch } : row))
  const removeRow = (i: number) => setRows(r => r.filter((_, idx) => idx !== i))

  const handleCreate = async () => {
    setFormError('')
    if (!name.trim()) { setFormError('Name is required'); return }
    const condition: Record<string, number> = {}
    for (const row of rows) {
      const num = Number(row.value)
      if (!row.field || !row.op || Number.isNaN(num)) { setFormError('Every condition needs a field, operator, and numeric value'); return }
      condition[`${row.field}__${row.op}`] = num
    }
    try {
      await api.createAlert(name.trim(), condition, symbol.trim() || undefined)
      setName(''); setSymbol(''); setRows([{ field: 'score', op: 'gt', value: '80' }])
      await mutate()
    } catch (e) {
      setFormError(e instanceof Error ? e.message : 'Failed to create alert')
    }
  }

  const handleToggle = async (alert: AlertDTO) => {
    await api.toggleAlert(alert.id, !alert.is_active)
    await mutate()
  }

  const handleDelete = async (id: number) => {
    await api.deleteAlert(id)
    await mutate()
  }

  const handleEvaluate = async () => {
    setEvaluating(true)
    try {
      await api.evaluateAlerts()
      await mutate()
    } finally {
      setEvaluating(false)
    }
  }

  return (
    <div className="flex flex-col h-full p-4 gap-3 overflow-hidden">
      <div className="flex items-center gap-3 shrink-0">
        <h1 className="text-base font-semibold tracking-wide">Alerts</h1>
        <button
          onClick={handleEvaluate}
          disabled={evaluating}
          className="ml-auto px-3 py-1.5 rounded-lg text-xs bg-blue/15 text-blue hover:bg-blue/25 transition-colors disabled:opacity-50"
        >
          {evaluating ? 'Evaluating…' : 'Run evaluation now'}
        </button>
      </div>

      <div className="flex-1 grid grid-cols-1 lg:grid-cols-[320px_1fr] gap-3 min-h-0 overflow-hidden">
        {/* Create form */}
        <div className="bg-surface border border-border rounded-xl p-3 flex flex-col gap-2.5 overflow-y-auto">
          <div className="text-[9px] text-dim uppercase tracking-wide">New Alert</div>
          <input
            value={name} onChange={e => setName(e.target.value)}
            placeholder="Alert name…"
            className="bg-bg border border-border rounded-lg px-3 py-1.5 text-xs text-primary placeholder:text-dim"
          />
          <input
            value={symbol} onChange={e => setSymbol(e.target.value.toUpperCase())}
            placeholder="Symbol (blank = whole universe)…"
            className="bg-bg border border-border rounded-lg px-3 py-1.5 text-xs text-primary placeholder:text-dim"
          />

          <div className="flex flex-col gap-1.5">
            {rows.map((row, i) => (
              <div key={i} className="flex items-center gap-1">
                <select
                  value={row.field} onChange={e => updateRow(i, { field: e.target.value })}
                  className="flex-1 bg-bg border border-border rounded px-1.5 py-1 text-[11px] text-primary min-w-0"
                >
                  {FIELDS.map(f => <option key={f} value={f}>{f}</option>)}
                </select>
                <select
                  value={row.op} onChange={e => updateRow(i, { op: e.target.value })}
                  className="bg-bg border border-border rounded px-1.5 py-1 text-[11px] text-primary"
                >
                  {OPERATORS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
                <input
                  value={row.value} onChange={e => updateRow(i, { value: e.target.value })}
                  placeholder="value"
                  className="w-16 bg-bg border border-border rounded px-1.5 py-1 text-[11px] text-primary placeholder:text-dim"
                />
                {rows.length > 1 && (
                  <button onClick={() => removeRow(i)} className="text-dim hover:text-red text-xs px-1">✕</button>
                )}
              </div>
            ))}
            <button onClick={addRow} className="text-[10px] text-blue text-left hover:text-blue/80">
              + AND condition
            </button>
          </div>

          {formError && <div className="text-[10px] text-red">{formError}</div>}

          <button
            onClick={handleCreate}
            className="px-3 py-1.5 rounded-lg text-xs bg-blue text-white font-medium hover:bg-blue/90 transition-colors"
          >
            Create Alert
          </button>
        </div>

        {/* Alert list */}
        <div className="bg-surface border border-border rounded-xl flex flex-col min-h-0 overflow-hidden">
          <div className="flex-1 overflow-y-auto min-h-0">
            {(alerts ?? []).length === 0 && (
              <div className="flex flex-col items-center justify-center h-full gap-2 text-dim">
                <span className="text-2xl opacity-30">🔔</span>
                <span className="text-sm">No alerts yet</span>
              </div>
            )}
            {(alerts ?? []).map(a => (
              <div key={a.id} className="border-b border-border/50">
                <div className="px-4 py-3 flex items-center gap-3">
                  <button
                    onClick={() => handleToggle(a)}
                    className={clsx('w-2 h-2 rounded-full shrink-0',
                      a.is_active ? 'bg-green' : 'bg-dim')}
                    title={a.is_active ? 'Active — click to disable' : 'Disabled — click to enable'}
                  />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium truncate">
                      {a.name} {a.symbol && <span className="text-dim font-mono text-xs">({a.symbol})</span>}
                    </div>
                    <div className="text-[10px] text-dim font-mono truncate">
                      {Object.entries(a.condition).map(([k, v]) => k.replace('__', ' ') + ' ' + v).join(' AND ')}
                    </div>
                  </div>
                  <span className="text-[10px] text-dim shrink-0">
                    {a.triggered_at ? `last fired ${new Date(a.triggered_at).toLocaleTimeString('en-IN')}` : 'never fired'}
                  </span>
                  <button
                    onClick={() => setExpandedId(expandedId === a.id ? null : a.id)}
                    className="text-[10px] text-blue shrink-0"
                  >
                    {expandedId === a.id ? 'hide' : 'history'}
                  </button>
                  <button
                    onClick={() => handleDelete(a.id)}
                    className="text-[10px] text-red shrink-0"
                  >
                    delete
                  </button>
                </div>
                {expandedId === a.id && (
                  <div className="bg-white/3">
                    <TriggerHistory alertId={a.id} />
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
