import { useState, useEffect, useRef } from 'react'
import { createChart, ColorType, CrosshairMode } from 'lightweight-charts'
import type { IChartApi, ISeriesApi } from 'lightweight-charts'
import { api } from '../api'
import type { ChartResponse } from '../types'
import clsx from 'clsx'

const SYMBOLS = [
  'RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'ICICIBANK',
  'SBIN', 'AXISBANK', 'WIPRO', 'TATAMOTORS', 'ITC',
  'NIFTY50', 'BANKNIFTY',
]

const INTERVALS = [
  { label: '1D',  value: 'day',       days: 365 },
  { label: '1H',  value: '60minute',  days: 7   },
  { label: '15M', value: '30minute',  days: 3   },
]

export default function Chart() {
  const [symbol,   setSymbol]   = useState('NIFTY50')
  const [interval, setInterval] = useState(INTERVALS[0])
  const [data,     setData]     = useState<ChartResponse | null>(null)
  const [loading,  setLoading]  = useState(false)
  const [error,    setError]    = useState('')

  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef     = useRef<IChartApi | null>(null)
  const candleRef    = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const volRef       = useRef<ISeriesApi<'Histogram'> | null>(null)

  // Fetch data
  useEffect(() => {
    setLoading(true)
    setError('')
    api.chart(symbol, interval.value, interval.days)
      .then(d => { setData(d); setError('') })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [symbol, interval])

  // Build / update chart
  useEffect(() => {
    if (!containerRef.current) return

    // Create chart once
    if (!chartRef.current) {
      const chart = createChart(containerRef.current, {
        layout: {
          background: { type: ColorType.Solid, color: '#161b27' },
          textColor: '#8892a4',
        },
        grid: {
          vertLines: { color: '#252d3d' },
          horzLines: { color: '#252d3d' },
        },
        crosshair: { mode: CrosshairMode.Normal },
        rightPriceScale: { borderColor: '#252d3d' },
        timeScale: {
          borderColor: '#252d3d',
          timeVisible: true,
          secondsVisible: false,
        },
        width:  containerRef.current.clientWidth,
        height: 480,
      })

      candleRef.current = chart.addCandlestickSeries({
        upColor:         '#10b981',
        downColor:       '#f43f5e',
        borderVisible:   false,
        wickUpColor:     '#10b981',
        wickDownColor:   '#f43f5e',
      })

      volRef.current = chart.addHistogramSeries({
        color:        '#3b82f6',
        priceFormat:  { type: 'volume' },
        priceScaleId: 'vol',
      })

      chart.priceScale('vol').applyOptions({
        scaleMargins: { top: 0.85, bottom: 0 },
      })

      chartRef.current = chart

      const handleResize = () => {
        if (containerRef.current)
          chart.applyOptions({ width: containerRef.current.clientWidth })
      }
      window.addEventListener('resize', handleResize)
      return () => {
        window.removeEventListener('resize', handleResize)
        chart.remove()
        chartRef.current = null
        candleRef.current = null
        volRef.current = null
      }
    }
  }, [])

  // Feed data into chart
  useEffect(() => {
    if (!data || !candleRef.current || !volRef.current) return
    candleRef.current.setData(
      data.candles.map(c => ({
        time:  c.time as any,
        open:  c.open,
        high:  c.high,
        low:   c.low,
        close: c.close,
      }))
    )
    volRef.current.setData(
      data.candles.map(c => ({
        time:  c.time as any,
        value: c.volume,
        color: c.close >= c.open ? 'rgba(16,185,129,0.4)' : 'rgba(244,63,94,0.4)',
      }))
    )
    chartRef.current?.timeScale().fitContent()
  }, [data])

  const last = data?.candles[data.candles.length - 1]
  const prev = data?.candles[data.candles.length - 2]
  const chg  = last && prev ? (last.close - prev.close) / prev.close * 100 : 0

  return (
    <div className="p-6 space-y-4">
      {/* Controls */}
      <div className="flex flex-wrap items-center gap-3">
        <select
          value={symbol}
          onChange={e => setSymbol(e.target.value)}
          className="bg-surface border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue"
        >
          {SYMBOLS.map(s => <option key={s} value={s}>{s}</option>)}
        </select>

        <div className="flex rounded-lg border border-border overflow-hidden">
          {INTERVALS.map(iv => (
            <button
              key={iv.value}
              onClick={() => setInterval(iv)}
              className={clsx(
                'px-4 py-2 text-sm transition-colors',
                interval.value === iv.value
                  ? 'bg-blue text-white'
                  : 'text-dim hover:text-primary hover:bg-surface'
              )}
            >
              {iv.label}
            </button>
          ))}
        </div>

        {loading && <span className="text-xs text-dim animate-pulse">Loading…</span>}
        {error && <span className="text-xs text-red">{error}</span>}
      </div>

      {/* Stats strip */}
      {last && (
        <div className="flex gap-6 text-sm font-mono">
          <span className="font-semibold text-lg">
            ₹{last.close.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
          </span>
          <span className={chg >= 0 ? 'text-green' : 'text-red'}>
            {chg >= 0 ? '+' : ''}{chg.toFixed(2)}%
          </span>
          <span className="text-dim">O: ₹{last.open.toFixed(2)}</span>
          <span className="text-green">H: ₹{last.high.toFixed(2)}</span>
          <span className="text-red">L: ₹{last.low.toFixed(2)}</span>
          <span className="text-dim">Vol: {(last.volume / 1_000).toFixed(0)}K</span>
        </div>
      )}

      {/* Chart container */}
      <div className="bg-surface border border-border rounded-xl overflow-hidden">
        {error ? (
          <div className="flex items-center justify-center h-48 text-dim text-sm">
            {error.includes('422') || error.includes('404')
              ? 'Intraday data unavailable outside market hours'
              : `Error: ${error}`}
          </div>
        ) : (
          <div ref={containerRef} className="w-full" />
        )}
      </div>
    </div>
  )
}
