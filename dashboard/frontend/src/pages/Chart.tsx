import { useState, useEffect, useRef } from 'react'
import { useLocation } from 'react-router-dom'
import { createChart, ColorType, CrosshairMode } from 'lightweight-charts'
import type { IChartApi, ISeriesApi } from 'lightweight-charts'
import useSWR from 'swr'
import { api, fetcher } from '../api'
import type { ChartResponse, WatchlistResponse, UniverseResponse, WhyResponse } from '../types'
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

function WatchlistPanel({
  active, onSelect, prices,
}: {
  active: string
  onSelect: (sym: string) => void
  prices: WatchlistResponse
}) {
  const { data: universe } = useSWR<UniverseResponse>('/api/universe', fetcher, {
    revalidateOnFocus: false,
  })
  const [search, setSearch] = useState('')

  // All symbols: indices first, then all sector stocks
  const INDEX_SYMS = ['NIFTY50', 'BANKNIFTY', 'NIFTYIT', 'FINNIFTY']
  const allStocks  = universe?.sectors.flatMap(s => s.stocks) ?? []

  const q = search.toLowerCase()
  const filteredIndices = INDEX_SYMS.filter(s =>
    !q || s.toLowerCase().includes(q)
  )
  const filteredStocks = allStocks.filter(st =>
    !q || st.symbol.toLowerCase().includes(q) || st.name.toLowerCase().includes(q)
  )

  const totalCount = INDEX_SYMS.length + allStocks.length

  return (
    <div className="w-52 shrink-0 flex flex-col bg-surface border-l border-border overflow-hidden">
      {/* Header */}
      <div className="px-3 py-2 border-b border-border flex items-center justify-between shrink-0">
        <span className="text-xs font-semibold tracking-wide">MyStocks</span>
        <span className="text-[10px] text-dim">{totalCount}</span>
      </div>

      {/* Search */}
      <div className="px-2 py-1.5 border-b border-border shrink-0">
        <input
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Search…"
          className="w-full text-[11px] bg-bg border border-border/50 rounded px-2 py-1 focus:outline-none focus:border-blue placeholder:text-dim"
        />
      </div>

      {/* Column headers */}
      <div className="grid grid-cols-[1fr_60px_50px] px-3 py-1 border-b border-border/50 shrink-0">
        {['Symbol', 'LTP', 'Chg%'].map(h => (
          <span key={h} className="text-[9px] text-dim uppercase tracking-wide text-right first:text-left">{h}</span>
        ))}
      </div>

      {/* Stock rows */}
      <div className="flex-1 overflow-y-auto min-h-0">

        {/* Indices */}
        {filteredIndices.length > 0 && (
          <>
            <div className="px-3 py-1 text-[9px] text-dim uppercase tracking-wider bg-bg/40">Indices</div>
            {filteredIndices.map(sym => <StockRow key={sym} sym={sym} name={sym} active={active} prices={prices} onSelect={onSelect} />)}
          </>
        )}

        {/* Stocks grouped by sector */}
        {universe?.sectors.map(sec => {
          const rows = sec.stocks.filter(st =>
            !q || st.symbol.toLowerCase().includes(q) || st.name.toLowerCase().includes(q)
          )
          if (!rows.length) return null
          return (
            <div key={sec.sector}>
              <div className="px-3 py-1 flex items-center gap-1.5 text-[9px] text-dim uppercase tracking-wider bg-bg/40">
                <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: sec.color }} />
                {sec.sector}
              </div>
              {rows.map(st => (
                <StockRow key={st.symbol} sym={st.symbol} name={st.name} active={active} prices={prices} onSelect={onSelect} />
              ))}
            </div>
          )
        })}

        {filteredIndices.length === 0 && filteredStocks.length === 0 && (
          <div className="px-3 py-6 text-xs text-dim text-center">No matches</div>
        )}
      </div>
    </div>
  )
}

function StockRow({ sym, name, active, prices, onSelect }: {
  sym: string; name: string; active: string
  prices: WatchlistResponse; onSelect: (s: string) => void
}) {
  const p      = prices[sym]
  const ltp    = p?.ltp ?? 0
  const chgPct = p?.change_pct ?? 0
  const up     = chgPct >= 0
  const isActive = sym === active

  return (
    <button
      onClick={() => onSelect(sym)}
      className={clsx(
        'w-full grid grid-cols-[1fr_60px_50px] items-center px-3 py-1.5 border-b border-border/20 last:border-0 transition-colors text-left',
        isActive ? 'bg-blue/10' : 'hover:bg-white/3',
      )}
    >
      <div className="min-w-0">
        <div className={clsx('text-xs font-mono font-medium truncate', isActive ? 'text-blue' : 'text-primary')}>
          {sym}
        </div>
        {name !== sym && (
          <div className="text-[9px] text-dim truncate">{name}</div>
        )}
      </div>
      <span className="text-[11px] font-mono text-right tabular-nums">
        {ltp > 0 ? pr(ltp) : '—'}
      </span>
      <span className={clsx(
        'text-[11px] font-mono text-right tabular-nums',
        ltp > 0 ? (up ? 'text-green' : 'text-red') : 'text-dim',
      )}>
        {ltp > 0 ? `${chgPct >= 0 ? '+' : ''}${chgPct.toFixed(2)}%` : '—'}
      </span>
    </button>
  )
}

// ── Why is it moving? ────────────────────────────────────────────────────────

function WhyPanel({ symbol }: { symbol: string }) {
  const [open, setOpen] = useState(false)
  const { data, isLoading } = useSWR<WhyResponse>(
    open ? `/api/stocks/${symbol}/why` : null, fetcher,
  )

  return (
    <div className="w-72 shrink-0 flex flex-col bg-surface border-l border-border overflow-hidden">
      <button
        onClick={() => setOpen(o => !o)}
        className="px-3 py-2 border-b border-border flex items-center justify-between shrink-0 hover:bg-white/3 transition-colors"
      >
        <span className="text-xs font-semibold tracking-wide">Why is {symbol} moving?</span>
        <span className="text-[10px] text-dim">{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div className="flex-1 overflow-y-auto min-h-0 p-3 flex flex-col gap-3">
          {isLoading && <span className="text-xs text-dim animate-pulse">Loading…</span>}

          {data && (
            <>
              {data.signal && (
                <div className="flex items-center gap-2">
                  <span className={clsx('px-1.5 py-0.5 rounded text-[9px] font-bold uppercase',
                    data.signal.direction === 'bullish' ? 'bg-green/15 text-green'
                      : data.signal.direction === 'bearish' ? 'bg-red/15 text-red'
                      : 'bg-white/5 text-dim')}>
                    {data.signal.direction}
                  </span>
                  <span className="text-xs font-mono text-dim">
                    score {data.signal.score} · {data.signal.confidence.toFixed(0)}% confidence
                  </span>
                </div>
              )}

              <p className="text-xs text-primary leading-relaxed">{data.conclusion}</p>

              {data.drivers.length > 0 && (
                <div>
                  <div className="text-[9px] text-dim uppercase tracking-wide mb-1.5">Drivers</div>
                  <div className="flex flex-col gap-1">
                    {data.drivers.slice(0, 4).map(d => (
                      <div key={d.factor} className="flex items-center justify-between text-[11px]">
                        <span className="text-dim">{d.label}</span>
                        <span className="font-mono">+{d.contribution}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {data.historical_analogue && (
                <div>
                  <div className="text-[9px] text-dim uppercase tracking-wide mb-1.5">
                    Historical Analogue
                  </div>
                  <div className="text-[11px] text-dim leading-relaxed">
                    {data.historical_analogue.sample_count} similar {data.historical_analogue.event_type} events:{' '}
                    <span className="text-primary font-mono">{data.historical_analogue.win_rate_pct}%</span> closed
                    higher next day (median {data.historical_analogue.median_return_pct}%)
                  </div>
                </div>
              )}

              {data.recent_news.length > 0 && (
                <div>
                  <div className="text-[9px] text-dim uppercase tracking-wide mb-1.5">Recent News</div>
                  <div className="flex flex-col gap-2">
                    {data.recent_news.slice(0, 5).map((n, i) => (
                      <a
                        key={i} href={n.url} target="_blank" rel="noreferrer"
                        className="block text-[11px] text-primary hover:text-blue transition-colors leading-snug"
                      >
                        {n.headline}
                        <span className="block text-[9px] text-dim font-mono mt-0.5">{n.source}</span>
                      </a>
                    ))}
                  </div>
                </div>
              )}

              {!data.signal && data.recent_news.length === 0 && (
                <span className="text-xs text-dim">No scored signal or recent news for {symbol}.</span>
              )}
            </>
          )}
        </div>
      )}
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
  const { data: universe } = useSWR<UniverseResponse>('/api/universe', fetcher, {
    revalidateOnFocus: false,
  })

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
          <div className="flex items-center h-full border-r border-border px-3 gap-2 min-w-[180px]">
            <select
              value={symbol}
              onChange={e => setSymbol(e.target.value)}
              className="bg-transparent text-sm font-semibold focus:outline-none cursor-pointer max-w-[140px]"
            >
              <optgroup label="Indices">
                {['NIFTY50', 'BANKNIFTY', 'NIFTYIT', 'FINNIFTY'].map(s => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </optgroup>
              {universe?.sectors.map(sec => (
                <optgroup key={sec.sector} label={sec.sector}>
                  {sec.stocks.map(st => (
                    <option key={st.symbol} value={st.symbol}>{st.symbol} — {st.name}</option>
                  ))}
                </optgroup>
              ))}
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

      {/* ── Why is it moving? ────────────────────────────────────────────── */}
      <WhyPanel symbol={symbol} />

      {/* ── Right watchlist ─────────────────────────────────────────────── */}
      <WatchlistPanel
        active={symbol}
        onSelect={setSymbol}
        prices={livePrices}
      />
    </div>
  )
}
