import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import useSWR from 'swr'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeSlug from 'rehype-slug'
import clsx from 'clsx'
import { api, fetcher } from '../api'
import type { DocBook, DocChapter, DocSearchHit } from '../types'

const ROMAN = ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X']

/** Resolve a relative link (e.g. "../reference/configuration.md") against the current chapter's folder. */
function resolveDocPath(current: string, href: string): string {
  const parts = current.split('/').slice(0, -1)
  for (const seg of href.split('/')) {
    if (seg === '..') parts.pop()
    else if (seg && seg !== '.') parts.push(seg)
  }
  return parts.join('/')
}

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return v
}

export default function Docs() {
  const params = useParams()
  const navigate = useNavigate()
  const scrollRef = useRef<HTMLDivElement>(null)
  const [query, setQuery] = useState('')
  const [activeSection, setActiveSection] = useState('')
  const [tocOpen, setTocOpen] = useState(true)
  const debounced = useDebounced(query.trim(), 250)

  const { data: book } = useSWR<DocBook>('/api/doc-files', fetcher)
  const chapters = useMemo(() => book?.parts.flatMap(p => p.chapters) ?? [], [book])
  const current = params['*'] || chapters[0]?.path || ''
  const index = chapters.findIndex(c => c.path === current)
  const chapter: DocChapter | undefined = chapters[index]
  const partIndex = book?.parts.findIndex(p => p.chapters.some(c => c.path === current)) ?? -1
  const prev = index > 0 ? chapters[index - 1] : undefined
  const next = index >= 0 && index < chapters.length - 1 ? chapters[index + 1] : undefined

  const { data: content, error } = useSWR(current ? ['doc', current] : null, () => api.docFile(current))
  const { data: hits } = useSWR<DocSearchHit[]>(
    debounced.length >= 2 ? ['doc-search', debounced] : null,
    () => api.docSearch(debounced),
  )

  // Jump to the #section (if any) once the chapter renders, otherwise to the top.
  useEffect(() => {
    if (!content) return
    const id = decodeURIComponent(window.location.hash.slice(1))
    const el = id ? document.getElementById(id) : null
    if (el) el.scrollIntoView()
    else scrollRef.current?.scrollTo({ top: 0 })
    setActiveSection(id)
  }, [content, current])

  // Highlight the section being read in the table of contents.
  useEffect(() => {
    const root = scrollRef.current
    if (!content || !root) return
    const headings = Array.from(root.querySelectorAll('article h2[id]'))
    const onScroll = () => {
      const top = root.getBoundingClientRect().top + 80
      let id = ''
      for (const h of headings) {
        if (h.getBoundingClientRect().top <= top) id = h.id
      }
      setActiveSection(id)
    }
    root.addEventListener('scroll', onScroll, { passive: true })
    return () => root.removeEventListener('scroll', onScroll)
  }, [content, current])

  const goTo = (path: string, hash = '') => {
    navigate(`/docs/${path}${hash ? `#${hash}` : ''}`)
    if (hash && path === current) {
      document.getElementById(hash)?.scrollIntoView({ behavior: 'smooth' })
      setActiveSection(hash)
    }
  }

  return (
    <div className="flex h-full select-text">
      {/* ── Table of contents ──────────────────────────────────────────── */}
      {tocOpen && (
        <aside className="w-72 shrink-0 h-full overflow-y-auto border-r border-border bg-surface/50 px-3 py-4">
          <div className="px-2 pb-3">
            <div className="text-base font-semibold text-primary">{book?.title ?? 'Documentation'}</div>
            {book?.subtitle && <div className="text-[13px] text-dim mt-0.5">{book.subtitle}</div>}
          </div>
          <input
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Search the handbook…"
            className="w-full mb-3 px-3 py-1.5 rounded-lg bg-bg border border-border text-sm text-primary placeholder:text-dim/60 focus:outline-none focus:border-blue/50"
          />

          {debounced.length >= 2 ? (
            <div className="space-y-1">
              <div className="px-2 pb-1 text-[12px] font-mono text-dim">
                {hits ? `${hits.length}${hits.length >= 40 ? '+' : ''} results` : 'Searching…'}
              </div>
              {hits?.map((h, i) => (
                <button
                  key={i}
                  onClick={() => goTo(h.path, h.section_id)}
                  className="block w-full text-left px-2 py-1.5 rounded-lg hover:bg-white/5"
                >
                  <div className="text-[12px] text-blue truncate">
                    {h.number}. {h.chapter}{h.section && ` › ${h.section}`}
                  </div>
                  <div className="text-[13px] text-dim leading-snug line-clamp-2">{h.snippet}</div>
                </button>
              ))}
            </div>
          ) : (
            book?.parts.map((part, pi) => (
              <div key={part.title} className="mb-4">
                <div className="px-2 pb-1 text-[11px] font-mono tracking-widest text-dim/80 uppercase">
                  {part.title === 'Other documents' ? part.title : `Part ${ROMAN[pi] ?? pi + 1} · ${part.title}`}
                </div>
                {part.chapters.map(ch => {
                  const isCurrent = ch.path === current
                  return (
                    <div key={ch.path}>
                      <Link
                        to={`/docs/${ch.path}`}
                        className={clsx(
                          'flex gap-2 px-2 py-1.5 rounded-lg text-sm transition-colors',
                          isCurrent ? 'bg-blue/15 text-blue font-medium' : 'text-dim hover:text-primary hover:bg-white/5',
                        )}
                      >
                        <span className="w-6 shrink-0 text-right font-mono text-[12px] opacity-70 pt-px">{ch.number}</span>
                        <span>{ch.title}</span>
                      </Link>
                      {isCurrent && ch.sections.length > 0 && (
                        <div className="ml-8 my-1 border-l border-border">
                          {ch.sections.map((s, si) => (
                            <button
                              key={s.id}
                              onClick={() => goTo(ch.path, s.id)}
                              className={clsx(
                                'flex gap-2 w-full text-left pl-3 pr-2 py-1 text-[13px] leading-snug -ml-px border-l',
                                activeSection === s.id
                                  ? 'border-blue text-primary'
                                  : 'border-transparent text-dim hover:text-primary',
                              )}
                            >
                              <span className="shrink-0 font-mono text-[11px] opacity-60 pt-px">{ch.number}.{si + 1}</span>
                              <span>{s.title}</span>
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            ))
          )}
        </aside>
      )}

      {/* ── Chapter ────────────────────────────────────────────────────── */}
      <div ref={scrollRef} className="flex-1 min-w-0 h-full overflow-y-auto">
        <div className="max-w-4xl px-10 py-6">
          <div className="flex items-center gap-3 mb-6 text-[12px] font-mono text-dim">
            <button
              onClick={() => setTocOpen(o => !o)}
              className="px-2 py-1 rounded border border-border hover:text-primary hover:border-blue/40"
              title={tocOpen ? 'Hide contents' : 'Show contents'}
            >
              {tocOpen ? '◧ Hide contents' : '◨ Contents'}
            </button>
            {chapter && partIndex >= 0 && book && (
              <span>
                {book.parts[partIndex].title === 'Other documents'
                  ? 'Other documents'
                  : `Part ${ROMAN[partIndex] ?? partIndex + 1} · ${book.parts[partIndex].title}`}
                {'  ·  '}Chapter {chapter.number}
              </span>
            )}
          </div>

          {error && <div className="text-red">Could not load {current}: {String(error.message ?? error)}</div>}
          {!content && !error && <div className="text-dim">Loading…</div>}
          {content && (
            <article className="markdown">
              <Markdown
                remarkPlugins={[remarkGfm]}
                rehypePlugins={[rehypeSlug]}
                components={{
                  a: ({ href = '', children, ...rest }) => {
                    if (/^[a-z]+:/i.test(href)) {
                      return <a href={href} target="_blank" rel="noreferrer" {...rest}>{children}</a>
                    }
                    if (href.startsWith('#')) {
                      return (
                        <a href={href} {...rest} onClick={e => {
                          e.preventDefault()
                          goTo(current, decodeURIComponent(href.slice(1)))
                        }}>{children}</a>
                      )
                    }
                    const [path, hash] = href.split('#')
                    if (path.endsWith('.md')) {
                      const target = resolveDocPath(current, path)
                      return (
                        <a href={`/docs/${target}${hash ? `#${hash}` : ''}`} {...rest}
                           onClick={e => { e.preventDefault(); goTo(target, hash) }}>
                          {children}
                        </a>
                      )
                    }
                    return <a href={href} {...rest}>{children}</a>
                  },
                }}
              >
                {content}
              </Markdown>
            </article>
          )}

          {/* Previous / next chapter */}
          {content && (prev || next) && (
            <nav className="grid grid-cols-2 gap-4 mt-14 pt-6 border-t border-border">
              <div>
                {prev && (
                  <Link to={`/docs/${prev.path}`} className="block p-4 rounded-lg border border-border hover:border-blue/40 hover:bg-white/[0.02]">
                    <div className="text-[12px] font-mono text-dim">← Chapter {prev.number}</div>
                    <div className="text-primary mt-1">{prev.title}</div>
                  </Link>
                )}
              </div>
              <div>
                {next && (
                  <Link to={`/docs/${next.path}`} className="block p-4 rounded-lg border border-border hover:border-blue/40 hover:bg-white/[0.02] text-right">
                    <div className="text-[12px] font-mono text-dim">Chapter {next.number} →</div>
                    <div className="text-primary mt-1">{next.title}</div>
                  </Link>
                )}
              </div>
            </nav>
          )}
          <div className="h-16" />
        </div>
      </div>
    </div>
  )
}
