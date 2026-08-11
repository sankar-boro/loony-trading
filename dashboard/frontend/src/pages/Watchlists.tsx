import { useState } from 'react'
import useSWR from 'swr'
import { api, fetcher } from '../api'
import type { WatchlistDTO } from '../types'

export default function Watchlists() {
  const { data: watchlists, mutate } = useSWR<WatchlistDTO[]>('/api/watchlists', fetcher)
  const [newName, setNewName] = useState('')
  const [activeId, setActiveId] = useState<number | null>(null)
  const [symbolInput, setSymbolInput] = useState('')

  const lists = watchlists ?? []
  const active = lists.find(w => w.id === activeId) ?? lists[0]

  const handleCreate = async () => {
    if (!newName.trim()) return
    const created = await api.createWatchlist(newName.trim())
    setNewName('')
    setActiveId(created.id)
    await mutate()
  }

  const handleDelete = async (id: number) => {
    await api.deleteWatchlist(id)
    if (activeId === id) setActiveId(null)
    await mutate()
  }

  const handleAddSymbol = async () => {
    if (!active || !symbolInput.trim()) return
    try {
      await api.addWatchlistItem(active.id, symbolInput.trim().toUpperCase())
      setSymbolInput('')
      await mutate()
    } catch {
      // unknown symbol — surfaced by the input staying filled
    }
  }

  const handleRemoveSymbol = async (symbol: string) => {
    if (!active) return
    await api.removeWatchlistItem(active.id, symbol)
    await mutate()
  }

  return (
    <div className="flex flex-col h-full p-4 gap-3 overflow-hidden">
      <div className="flex items-center gap-3 shrink-0">
        <h1 className="text-base font-semibold tracking-wide">Watchlists</h1>
      </div>

      <div className="flex-1 grid grid-cols-1 lg:grid-cols-[220px_1fr] gap-3 min-h-0 overflow-hidden">
        {/* List of watchlists */}
        <div className="bg-surface border border-border rounded-xl flex flex-col min-h-0 overflow-hidden">
          <div className="flex-1 overflow-y-auto min-h-0">
            {lists.map(w => (
              <button
                key={w.id} onClick={() => setActiveId(w.id)}
                className={`w-full text-left px-3 py-2.5 border-b border-border/50 text-sm transition-colors ${
                  (active?.id === w.id) ? 'bg-blue/10 text-blue' : 'text-primary hover:bg-white/3'
                }`}
              >
                <div className="font-medium">{w.name}</div>
                <div className="text-[10px] text-dim">{w.symbols.length} symbols</div>
              </button>
            ))}
            {lists.length === 0 && (
              <div className="p-4 text-xs text-dim">No watchlists yet.</div>
            )}
          </div>
          <div className="p-2 border-t border-border flex gap-1.5 shrink-0">
            <input
              value={newName}
              onChange={e => setNewName(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleCreate()}
              placeholder="New watchlist…"
              className="flex-1 bg-bg border border-border rounded-lg px-2 py-1.5 text-xs text-primary placeholder:text-dim min-w-0"
            />
            <button
              onClick={handleCreate}
              className="px-2.5 py-1.5 rounded-lg text-xs bg-blue/15 text-blue hover:bg-blue/25 transition-colors shrink-0"
            >
              Add
            </button>
          </div>
        </div>

        {/* Active watchlist detail */}
        <div className="bg-surface border border-border rounded-xl flex flex-col min-h-0 overflow-hidden">
          {!active ? (
            <div className="flex flex-col items-center justify-center h-full gap-2 text-dim">
              <span className="text-2xl opacity-30">◎</span>
              <span className="text-sm">Select or create a watchlist</span>
            </div>
          ) : (
            <>
              <div className="px-4 py-3 border-b border-border flex items-center justify-between shrink-0">
                <span className="text-sm font-medium">{active.name}</span>
                <button
                  onClick={() => handleDelete(active.id)}
                  className="text-[10px] text-red hover:text-red/80 transition-colors"
                >
                  Delete list
                </button>
              </div>

              <div className="p-3 border-b border-border flex gap-1.5 shrink-0">
                <input
                  value={symbolInput}
                  onChange={e => setSymbolInput(e.target.value.toUpperCase())}
                  onKeyDown={e => e.key === 'Enter' && handleAddSymbol()}
                  placeholder="Add symbol, e.g. RELIANCE…"
                  className="flex-1 bg-bg border border-border rounded-lg px-3 py-1.5 text-xs text-primary placeholder:text-dim"
                />
                <button
                  onClick={handleAddSymbol}
                  className="px-3 py-1.5 rounded-lg text-xs bg-blue/15 text-blue hover:bg-blue/25 transition-colors"
                >
                  Add
                </button>
              </div>

              <div className="flex-1 overflow-y-auto min-h-0 p-3">
                {active.symbols.length === 0 ? (
                  <div className="text-xs text-dim">No symbols yet.</div>
                ) : (
                  <div className="flex flex-wrap gap-2">
                    {active.symbols.map(sym => (
                      <div
                        key={sym}
                        className="flex items-center gap-1.5 bg-white/5 rounded-lg pl-3 pr-1.5 py-1.5"
                      >
                        <span className="text-xs font-mono text-primary">{sym}</span>
                        <button
                          onClick={() => handleRemoveSymbol(sym)}
                          className="text-dim hover:text-red transition-colors text-xs px-1"
                        >
                          ✕
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
