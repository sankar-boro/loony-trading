import { useState, useRef, useEffect } from 'react'
import { api } from '../api'
import clsx from 'clsx'

interface Message {
  role: 'user' | 'assistant'
  text: string
  confidence?: 'low' | 'medium' | 'high'
  evidence?: string[]
  insufficientEvidence?: boolean
}

const SUGGESTIONS = [
  'Which stocks have unusual volume today?',
  'Show bullish stocks',
  'Show bearish setups',
  'What are the latest market-moving events?',
  'Why is Reliance moving?',
]

function ConfidenceBadge({ confidence }: { confidence: 'low' | 'medium' | 'high' }) {
  const cls = confidence === 'high' ? 'bg-green/15 text-green'
    : confidence === 'medium' ? 'bg-amber-500/15 text-amber-400'
    : 'bg-white/5 text-dim'
  return (
    <span className={clsx('px-1.5 py-0.5 rounded text-[9px] font-bold uppercase', cls)}>
      {confidence} confidence
    </span>
  )
}

export default function Copilot() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  const ask = async (question: string) => {
    if (!question.trim() || loading) return
    setMessages(m => [...m, { role: 'user', text: question }])
    setInput('')
    setLoading(true)
    try {
      const res = await api.copilotQuery(question)
      setMessages(m => [...m, {
        role: 'assistant', text: res.answer, confidence: res.confidence,
        evidence: res.evidence, insufficientEvidence: res.insufficient_evidence,
      }])
    } catch {
      setMessages(m => [...m, { role: 'assistant', text: 'Request failed — is the backend running?' }])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex flex-col h-full p-4 gap-3 overflow-hidden">
      <div className="shrink-0">
        <h1 className="text-base font-semibold tracking-wide">Market Copilot</h1>
        <p className="text-xs text-dim mt-0.5">
          Answers are grounded in signals, news, and historical analogues already in the
          database — never invented. It says "insufficient evidence" when the data doesn't
          support an answer.
        </p>
      </div>

      <div className="flex-1 bg-surface border border-border rounded-xl flex flex-col min-h-0 overflow-hidden">
        <div className="flex-1 overflow-y-auto min-h-0 p-4 flex flex-col gap-3">
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center flex-1 gap-4 text-dim">
              <span className="text-2xl opacity-30">◈</span>
              <div className="flex flex-col gap-1.5 items-center">
                {SUGGESTIONS.map(s => (
                  <button
                    key={s} onClick={() => ask(s)}
                    className="text-xs px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 text-primary transition-colors"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((m, i) => (
            <div key={i} className={clsx('flex', m.role === 'user' ? 'justify-end' : 'justify-start')}>
              <div className={clsx(
                'max-w-[75%] rounded-xl px-3.5 py-2.5 text-sm leading-relaxed',
                m.role === 'user' ? 'bg-blue text-white' : 'bg-white/5 text-primary',
              )}>
                <p>{m.text}</p>

                {m.role === 'assistant' && m.confidence && (
                  <div className="mt-2 flex items-center gap-2 flex-wrap">
                    <ConfidenceBadge confidence={m.confidence} />
                    {m.insufficientEvidence && (
                      <span className="px-1.5 py-0.5 rounded text-[9px] font-bold uppercase bg-red/15 text-red">
                        Insufficient evidence
                      </span>
                    )}
                  </div>
                )}

                {m.evidence && m.evidence.length > 0 && (
                  <div className="mt-2 pt-2 border-t border-border/50">
                    <div className="text-[9px] text-dim uppercase tracking-wide mb-1">Evidence</div>
                    <ul className="flex flex-col gap-0.5">
                      {m.evidence.map((e, j) => (
                        <li key={j} className="text-[10px] text-dim font-mono">{e}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            </div>
          ))}

          {loading && (
            <div className="flex justify-start">
              <div className="bg-white/5 rounded-xl px-3.5 py-2.5 text-sm text-dim animate-pulse">
                Thinking…
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        <form
          onSubmit={e => { e.preventDefault(); ask(input) }}
          className="border-t border-border p-3 flex items-center gap-2 shrink-0"
        >
          <input
            value={input}
            onChange={e => setInput(e.target.value)}
            placeholder="Ask about signals, news, or why a stock is moving…"
            className="flex-1 bg-bg border border-border rounded-lg px-3 py-2 text-sm text-primary placeholder:text-dim focus:outline-none focus:border-blue"
          />
          <button
            type="submit" disabled={loading || !input.trim()}
            className="px-4 py-2 rounded-lg text-xs bg-blue text-white font-medium hover:bg-blue/90 transition-colors disabled:opacity-40"
          >
            Ask
          </button>
        </form>
      </div>
    </div>
  )
}
