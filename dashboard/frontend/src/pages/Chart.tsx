import { useState, useEffect, useRef } from 'react'
import { useLocation } from 'react-router-dom'
import { createChart, ColorType, CrosshairMode } from 'lightweight-charts'
import type { IChartApi, ISeriesApi } from 'lightweight-charts'
import { api } from '../api'
import type { ChartResponse, WatchlistResponse } from '../types'
import clsx from 'clsx'

// ── Constants ─────────────────────────────────────────────────────────────────

const INTERVALS = [
  { label: '1m',  value: '1minute',   days: 2   },
  { label: '5m',  value: '5minute',   days: 5   },
  { label: '15m', value: '15minute',  days: 7   },
  { label: '30m', value: '30minute',  days: 14  },
  { label: '1H',  value: '60minute',  days: 30  },
  { label: '1D',  value: 'day',       days: 365 },
  { label: '1W',  value: 'day',       days: 730 },
]

const RANGES = [
  { label: '5D',  days: 5   },
  { label: '1M',  days: 30  },
  { label: '3M',  days: 90  },
  { label: '6M',  days: 180 },
  { label: '1Y',  days: 365 },
  { label: '5Y',  days: 730 },
]

// Max days per native interval (Upstox limits)
const MAX_DAYS: Record<string, number> = {
  '1minute': 3, '5minute': 5, '15minute': 10,
  '30minute': 30, '60minute': 30, 'day': 730,
}

// Left toolbar tools (visual only — drawing tools require a plugin)
const TOOLS = [
  { icon: '⊹', title: 'Cursor' },
  { icon: '╱', title: 'Trend Line' },
  { icon: '━', title: 'Horizontal Line' },
  { icon: '□', title: 'Rectangle' },
  { icon: '◎', title: 'Circle' },
  { icon: 'T', title: 'Text' },
  { icon: '⌇', title: 'Fibonacci' },
]

const pr = (n: number) => n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

// ── Live price hook (SSE) ─────────────────────────────────────────────────────

function useLiveWatchlist() {
  const [prices, setPrices] = useState<WatchlistResponse>({})
  useEffect(() => {
    const es = new EventSource('/api/stream/prices')
    es.onmessage = (e) => {
      try {
        const d = JSON.parse(e.data)
        if (d?.watchlist) setPrices(d.watchlist)
      } catch {}
    }
    return () => es.close()
  }, [])
  return prices
}

// ── Watchlist panel ───────────────────────────────────────────────────────────

const WATCHLIST_SYMS = [
  'NIFTY50', 'BANKNIFTY',
  'RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'ICICIBANK',
  'SBIN', 'AXISBANK', 'KOTAKBANK', 'BAJFINANCE', 'BHARTIARTL',
  'WIPRO', 'HCLTECH', 'TITAN', 'ITC', 'SUNPHARMA',
  'TATAMOTORS', 'MARUTI', 'ULTRACEMCO',
]

function WatchlistPanel({
  active, onSelect, prices,
}: {
  active: string
  onSelect: (sym: string) => void
  prices: WatchlistResponse
}) {
  return (
    <div className="w-52 shrink-0 flex flex-col bg-surface border-l border-border overflow-hidden">
      {/* Header */}
      <div className="px-3 py-2 border-b border-border flex items-center justify-between">
        <span className="text-xs font-semibold tracking-wide">MyStocks</span>
        <span className="text-[10px] text-dim">∨</span>
      </div>

      {/* Column headers */}
      <div className="grid grid-cols-[1fr_64px_52px] px-3 py-1.5 border-b border-border/50">
        {['Symbol', 'LTP', 'Chg%'].map(h => (
          <span key={h} className="text-[9px] text-dim uppercase tracking-wide text-right first:text-left">{h}</span>
        ))}
      </div>

      {/* Stock rows */}
      <div className="flex-1 overflow-y-auto">
        {WATCHLIST_SYMS.map(sym => {
          const p      = prices[sym]
          const ltp    = p?.ltp ?? 0
          const chgPct = p?.change_pct ?? 0
          const up     = chgPct >= 0
          const isActive = sym === active

          return (
            <button
              key={sym}
              onClick={() => onSelect(sym)}
              className={clsx(
                'w-full grid grid-cols-[1fr_64px_52px] items-center px-3 py-2 border-b border-border/30 last:border-0 transition-colors text-left',
                isActive ? 'bg-blue/10' : 'hover:bg-white/3',
              )}
            >
              <span className={clsx(
                'text-xs font-mono font-medium truncate',
                isActive ? 'text-blue' : 'text-primary',
              )}>
                {sym}
              </span>
              <span className="text-xs font-mono text-right tabular-nums">
                {ltp > 0 ? pr(ltp) : '—'}
              </span>
              <span className={clsx(
                'text-xs font-mono text-right tabular-nums',
                ltp > 0 ? (up ? 'text-green' : 'text-red') : 'text-dim',
              )}>
                {ltp > 0 ? `${chgPct >= 0 ? '+' : ''}${chgPct.toFixed(2)}%` : '—'}
              </span>
            </button>
          )
        })}
      </div>
    </div>
  )
}

// ── Main Chart ────────────────────────────────────────────────────────────────

export default function Chart() {
  const location     = useLocation()
  const initialSym   = (location.state as { symbol?: string } | null)?.symbol ?? 'NIFTY50'

  const [symbol,    setSymbol]    = useState(initialSym)
  const [interval,  setInterval]  = useState(INTERVALS[5]) // default 1D
  const [rangeDays, setRangeDays] = useState(365)
  const [data,      setData]      = useState<ChartResponse | null>(null)
  const [loading,   setLoading]   = useState(false)
  const [error,     setError]     = useState('')
  const [activeTool, setActiveTool] = useState(0)

  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef     = useRef<IChartApi | null>(null)
  const candleRef    = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const volRef       = useRef<ISeriesApi<'Histogram'> | null>(null)

  const livePrices = useLiveWatchlist()

  // Effective days — cap to API limit
  const effectiveDays = Math.min(rangeDays, MAX_DAYS[interval.value] ?? 365)

  // Fetch candle data
  useEffect(() => {
    setLoading(true)
    setError('')
    api.chart(symbol, interval.value, effectiveDays)
      .then(d => { setData(d); setError('') })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [symbol, interval, effectiveDays])

  // Create chart
  useEffect(() => {
    if (!containerRef.current) return
    const el = containerRef.current

    const chart = createChart(el, {
      layout: {
        background: { type: ColorType.Solid, color: '#0f1117' },
        textColor: '#8892a4',
        fontSize: 11,
      },
      grid: {
        vertLines: { color: '#1a2030' },
        horzLines: { color: '#1a2030' },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: '#3b82f6', width: 1, style: 3, labelBackgroundColor: '#3b82f6' },
        horzLine: { color: '#3b82f6', width: 1, style: 3, labelBackgroundColor: '#3b82f6' },
      },
      rightPriceScale: {
        borderColor: '#252d3d',
        textColor: '#8892a4',
        scaleMargins: { top: 0.1, bottom: 0.1 },
      },
      timeScale: {
        borderColor: '#252d3d',
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 5,
        barSpacing: 8,
      },
      width:  el.clientWidth,
      height: el.clientHeight || 500,
    })

    candleRef.current = chart.addCandlestickSeries({
      upColor:         '#26a69a',
      downColor:       '#ef5350',
      borderUpColor:   '#26a69a',
      borderDownColor: '#ef5350',
      wickUpColor:     '#26a69a',
      wickDownColor:   '#ef5350',
    })

    volRef.current = chart.addHistogramSeries({
      color:        '#3b82f6',
      priceFormat:  { type: 'volume' },
      priceScaleId: 'vol',
    })

    chart.priceScale('vol').applyOptions({
      scaleMargins: { top: 0.82, bottom: 0 },
    })

    chartRef.current = chart

    const ro = new ResizeObserver(() => {
      if (el) chart.applyOptions({ width: el.clientWidth, height: el.clientHeight })
    })
    ro.observe(el)

    return () => {
      ro.disconnect()
      chart.remove()
      chartRef.current = null
      candleRef.current = null
      volRef.current = null
    }
  }, [])

  // Feed data
  useEffect(() => {
    if (!data || !candleRef.current || !volRef.current) return
    candleRef.current.setData(
      data.candles.map(c => ({ time: c.time as any, open: c.open, high: c.high, low: c.low, close: c.close }))
    )
    volRef.current.setData(
      data.candles.map(c => ({
        time:  c.time as any,
        value: c.volume,
        color: c.close >= c.open ? 'rgba(38,166,154,0.35)' : 'rgba(239,83,80,0.35)',
      }))
    )
    chartRef.current?.timeScale().fitContent()
  }, [data])

  const last  = data?.candles[data.candles.length - 1]
  const prev  = data?.candles[data.candles.length - 2]
  const chg   = last && prev ? last.close - prev.close : 0
  const chgPct = prev && prev.close ? (chg / prev.close) * 100 : 0
  const isUp  = chg >= 0

  return (
    <div className="flex h-full overflow-hidden bg-bg text-primary select-none">

      {/* ── Left toolbar ────────────────────────────────────────────────── */}
      <div className="w-10 shrink-0 flex flex-col items-center py-2 gap-0.5 bg-surface border-r border-border">
        {TOOLS.map((tool, i) => (
          <button
            key={i}
            title={tool.title}
            onClick={() => setActiveTool(i)}
            className={clsx(
              'w-8 h-8 flex items-center justify-center rounded text-sm transition-colors',
              activeTool === i
                ? 'bg-blue/20 text-blue'
                : 'text-dim hover:bg-white/5 hover:text-primary',
            )}
          >
            {tool.icon}
          </button>
        ))}

        <div className="flex-1" />

        {/* Bottom toolbar icons */}
        {['⊙', '✕'].map((icon, i) => (
          <button key={i}
            className="w-8 h-8 flex items-center justify-center rounded text-dim hover:bg-white/5 hover:text-primary transition-colors text-sm">
            {icon}
          </button>
        ))}
      </div>

      {/* ── Centre: top bar + chart + bottom bar ────────────────────────── */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">

        {/* Top bar */}
        <div className="h-10 shrink-0 flex items-center gap-0 border-b border-border bg-surface px-0">

          {/* Symbol selector */}
          <div className="flex items-center h-full border-r border-border px-3 gap-2 min-w-[200px]">
            <select
              value={symbol}
              onChange={e => setSymbol(e.target.value)}
              className="bg-transparent text-sm font-semibold focus:outline-none cursor-pointer"
            >
              {WATCHLIST_SYMS.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
            <span className="text-[10px] text-dim whitespace-nowrap">NSE</span>
          </div>

          {/* Interval buttons */}
          <div className="flex items-center h-full border-r border-border px-1 gap-0.5">
            {INTERVALS.map(iv => (
              <button
                key={iv.value + iv.days}
                onClick={() => setInterval(iv)}
                className={clsx(
                  'px-2.5 h-7 text-xs rounded transition-colors',
                  interval.value === iv.value && interval.label === iv.label
                    ? 'bg-blue text-white'
                    : 'text-dim hover:text-primary hover:bg-white/5',
                )}
              >
                {iv.label}
              </button>
            ))}
          </div>

          {/* OHLCV strip */}
          {last ? (
            <div className="flex items-center gap-3 px-3 text-xs font-mono overflow-x-auto flex-1">
              <span className={clsx('font-bold text-sm', isUp ? 'text-green' : 'text-red')}>
                {pr(last.close)}
              </span>
              <span className={isUp ? 'text-green' : 'text-red'}>
                {chg >= 0 ? '+' : ''}{chg.toFixed(2)} ({chgPct >= 0 ? '+' : ''}{chgPct.toFixed(2)}%)
              </span>
              <span className="text-dim whitespace-nowrap">O <span className="text-primary">{pr(last.open)}</span></span>
              <span className="text-dim whitespace-nowrap">H <span className="text-green">{pr(last.high)}</span></span>
              <span className="text-dim whitespace-nowrap">L <span className="text-red">{pr(last.low)}</span></span>
              <span className="text-dim whitespace-nowrap">Vol <span className="text-primary">{last.volume > 1_000_000 ? `${(last.volume / 1_000_000).toFixed(2)}M` : `${(last.volume / 1_000).toFixed(0)}K`}</span></span>
              {loading && <span className="text-dim animate-pulse ml-2">●</span>}
            </div>
          ) : (
            <div className="flex-1 flex items-center px-3">
              {loading && <span className="text-xs text-dim animate-pulse">Loading…</span>}
              {error && <span className="text-xs text-red">{error}</span>}
            </div>
          )}
        </div>

        {/* Chart area */}
        <div className="flex-1 min-h-0 relative overflow-hidden">
          {error && !loading ? (
            <div className="absolute inset-0 flex items-center justify-center text-dim text-sm">
              {error}
            </div>
          ) : (
            <div ref={containerRef} className="w-full h-full" />
          )}
        </div>

        {/* Bottom bar: range + status */}
        <div className="h-8 shrink-0 flex items-center gap-1 px-3 border-t border-border bg-surface">
          {/* Range buttons */}
          <div className="flex items-center gap-0.5">
            {RANGES.map(r => (
              <button
                key={r.label}
                onClick={() => setRangeDays(r.days)}
                className={clsx(
                  'px-2.5 h-6 text-xs rounded transition-colors',
                  rangeDays === r.days
                    ? 'bg-blue/20 text-blue font-medium'
                    : 'text-dim hover:text-primary hover:bg-white/5',
                )}
              >
                {r.label}
              </button>
            ))}
          </div>

          <div className="flex-1" />

          {/* Status */}
          <span className="text-[10px] text-dim font-mono">
            {data?.candles.length ?? 0} bars · {interval.label}
          </span>
          <span className="text-[10px] text-dim font-mono ml-3">
            Powered by TBT
          </span>
        </div>
      </div>

      {/* ── Right watchlist ─────────────────────────────────────────────── */}
      <WatchlistPanel
        active={symbol}
        onSelect={setSymbol}
        prices={livePrices}
      />
    </div>
  )
}
