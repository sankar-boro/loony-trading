import { useState } from 'react'
import useSWR from 'swr'
import { api, fetcher } from '../api'
import type { NewsItem } from '../types'
import clsx from 'clsx'

const EVENT_LABELS: Record<string, string> = {
  earnings: 'Earnings', revenue: 'Revenue', profit_warning: 'Profit Warning',
  guidance: 'Guidance', management_change: 'Management Change', ma: 'M&A',
  acquisition: 'Acquisition', partnership: 'Partnership', contract_win: 'Contract Win',
  order_win: 'Order Win', regulatory_approval: 'Regulatory Approval',
  regulatory_action: 'Regulatory Action', government_policy: 'Government Policy',
  product_launch: 'Product Launch', litigation: 'Litigation', debt: 'Debt',
  credit_rating: 'Credit Rating', dividend: 'Dividend', buyback: 'Buyback',
  promoter_activity: 'Promoter Activity', insider_activity: 'Insider Activity',
  fii_dii_activity: 'FII/DII Activity', brokerage_upgrade: 'Brokerage Upgrade',
  brokerage_downgrade: 'Brokerage Downgrade', sector_news: 'Sector News',
  macro_news: 'Macro News', commodity_shock: 'Commodity Shock',
  currency_shock: 'Currency Shock', geopolitical_event: 'Geopolitical Event',
  other: 'Other',
}

function timeAgo(iso: string) {
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60_000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.round(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.round(hrs / 24)}d ago`
}

function SentimentBadge({ score }: { score: number }) {
  const label = score > 0.15 ? 'Bullish' : score < -0.15 ? 'Bearish' : 'Neutral'
  const cls = score > 0.15
    ? 'bg-green/15 text-green'
    : score < -0.15 ? 'bg-red/15 text-red' : 'bg-white/5 text-dim'
  return <span className={clsx('px-1.5 py-0.5 rounded text-[9px] font-bold', cls)}>{label}</span>
}

function NewsCard({ item }: { item: NewsItem }) {
  return (
    <div className="bg-surface border border-border rounded-xl p-4 flex flex-col gap-2">
      <div className="flex items-start justify-between gap-3">
        <a
          href={item.url} target="_blank" rel="noreferrer"
          className="text-sm font-medium text-primary hover:text-blue transition-colors"
        >
          {item.headline}
        </a>
        <span className="text-[10px] text-dim font-mono whitespace-nowrap shrink-0">
          {timeAgo(item.published_at)}
        </span>
      </div>

      {item.summary && <p className="text-xs text-dim leading-relaxed">{item.summary}</p>}

      <div className="flex items-center flex-wrap gap-2 mt-1">
        <span className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-blue/15 text-blue">
          {EVENT_LABELS[item.event_type] ?? item.event_type}
        </span>
        <SentimentBadge score={item.sentiment_score} />
        <span className="text-[9px] text-dim font-mono">catalyst {(item.impact_score * 10).toFixed(1)}/10</span>
        <span className="text-[9px] text-dim font-mono">conf {(item.confidence * 100).toFixed(0)}%</span>
        {item.affected_stocks.map(s => (
          <span key={s} className="px-1.5 py-0.5 rounded text-[9px] font-mono bg-white/5 text-primary">{s}</span>
        ))}
      </div>

      <div className="text-[10px] text-dim/70 font-mono">{item.source}</div>
    </div>
  )
}

export default function News() {
  const [eventType, setEventType] = useState('')
  const [symbol, setSymbol] = useState('')
  const [ingesting, setIngesting] = useState(false)

  const { data: eventTypes } = useSWR<string[]>('/api/news/event-types', fetcher)

  const params = new URLSearchParams()
  if (eventType) params.set('event_type', eventType)
  if (symbol) params.set('symbol', symbol)
  const qs = params.toString()

  const { data: news, isLoading, mutate } = useSWR<NewsItem[]>(
    `/api/news${qs ? `?${qs}` : ''}`, fetcher, { refreshInterval: 30_000 },
  )

  const handleIngest = async () => {
    setIngesting(true)
    try {
      await api.ingestNews()
      await mutate()
    } finally {
      setIngesting(false)
    }
  }

  return (
    <div className="flex flex-col h-full p-4 gap-3 overflow-hidden">
      <div className="flex items-center gap-3 shrink-0 flex-wrap">
        <h1 className="text-base font-semibold tracking-wide">News Terminal</h1>

        <select
          value={eventType}
          onChange={e => setEventType(e.target.value)}
          className="bg-surface border border-border rounded-lg px-3 py-1.5 text-xs text-primary"
        >
          <option value="">All events</option>
          {(eventTypes ?? []).map(et => (
            <option key={et} value={et}>{EVENT_LABELS[et] ?? et}</option>
          ))}
        </select>

        <input
          value={symbol}
          onChange={e => setSymbol(e.target.value.toUpperCase())}
          placeholder="Filter by symbol..."
          className="bg-surface border border-border rounded-lg px-3 py-1.5 text-xs text-primary placeholder:text-dim w-40"
        />

        <button
          onClick={handleIngest}
          disabled={ingesting}
          className="ml-auto px-3 py-1.5 rounded-lg text-xs bg-blue/15 text-blue hover:bg-blue/25 transition-colors disabled:opacity-50"
        >
          {ingesting ? 'Fetching…' : 'Fetch latest'}
        </button>
      </div>

      <div className="flex-1 overflow-y-auto min-h-0">
        {isLoading && <span className="text-xs text-dim animate-pulse">Loading…</span>}

        {!isLoading && (news ?? []).length === 0 && (
          <div className="flex flex-col items-center justify-center h-full gap-2 text-dim">
            <span className="text-2xl opacity-30">◈</span>
            <span className="text-sm">No news yet</span>
            <button onClick={handleIngest} className="text-xs text-blue mt-1">Fetch latest news</button>
          </div>
        )}

        <div className="flex flex-col gap-2">
          {(news ?? []).map(item => <NewsCard key={item.id} item={item} />)}
        </div>
      </div>
    </div>
  )
}
