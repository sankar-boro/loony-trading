import { useEffect, useRef } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import useSWR from 'swr'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeSlug from 'rehype-slug'
import clsx from 'clsx'
import { api, fetcher } from '../api'
import type { DocFile } from '../types'

const DEFAULT_DOC = 'quickstart.md'

/** Resolve a relative link (e.g. "../features.md#x") against the current doc's folder. */
function resolveDocPath(current: string, href: string): string {
  const parts = current.split('/').slice(0, -1)
  for (const seg of href.split('/')) {
    if (seg === '..') parts.pop()
    else if (seg && seg !== '.') parts.push(seg)
  }
  return parts.join('/')
}

export default function Docs() {
  const params = useParams()
  const navigate = useNavigate()
  const contentRef = useRef<HTMLDivElement>(null)

  const { data: files } = useSWR<DocFile[]>('/api/doc-files', fetcher)
  const current = params['*'] || (files?.some(f => f.path === DEFAULT_DOC) ? DEFAULT_DOC : files?.[0]?.path) || ''

  const { data: content, error } = useSWR(
    current ? ['doc', current] : null,
    () => api.docFile(current),
  )

  // Jump to the #anchor (if any) once the doc renders, otherwise to the top.
  useEffect(() => {
    if (!content) return
    const id = decodeURIComponent(window.location.hash.slice(1))
    const el = id ? document.getElementById(id) : null
    if (el) el.scrollIntoView()
    else contentRef.current?.scrollIntoView()
  }, [content, current])

  const folders = new Map<string, DocFile[]>()
  for (const f of files ?? []) {
    const dir = f.path.includes('/') ? f.path.slice(0, f.path.lastIndexOf('/')) : ''
    folders.set(dir, [...(folders.get(dir) ?? []), f])
  }

  return (
    <div className="flex min-h-full select-text">
      {/* ── Doc list ─────────────────────────────────────────────────────── */}
      <aside className="w-60 shrink-0 border-r border-border bg-surface/50 px-2 py-4 sticky top-0 self-start max-h-screen overflow-y-auto">
        <div className="px-3 pb-3 text-[12px] font-mono tracking-widest text-dim">DOCS</div>
        {[...folders.entries()].map(([dir, list]) => (
          <div key={dir} className="mb-3">
            {dir && <div className="px-3 pt-2 pb-1 text-[12px] font-mono text-dim/70">{dir}/</div>}
            {list.map(f => (
              <Link
                key={f.path}
                to={`/docs/${f.path}`}
                title={f.path}
                className={clsx(
                  'block px-3 py-1.5 rounded-lg text-sm truncate transition-colors',
                  f.path === current
                    ? 'bg-blue/15 text-blue font-medium'
                    : 'text-dim hover:text-primary hover:bg-white/5',
                )}
              >
                {f.title}
              </Link>
            ))}
          </div>
        ))}
      </aside>

      {/* ── Rendered markdown ────────────────────────────────────────────── */}
      <div ref={contentRef} className="flex-1 min-w-0 px-10 py-8">
        {current && <div className="mb-4 text-[12px] font-mono text-dim">docs/{current}</div>}
        {error && <div className="text-red">Could not load {current}: {String(error.message ?? error)}</div>}
        {!content && !error && <div className="text-dim">Loading…</div>}
        {content && (
          <article className="markdown max-w-4xl">
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
                        document.getElementById(decodeURIComponent(href.slice(1)))?.scrollIntoView({ behavior: 'smooth' })
                        window.history.replaceState(null, '', href)
                      }}>{children}</a>
                    )
                  }
                  const [path, hash] = href.split('#')
                  if (path.endsWith('.md')) {
                    const target = `/docs/${resolveDocPath(current, path)}${hash ? `#${hash}` : ''}`
                    return (
                      <a href={target} {...rest} onClick={e => { e.preventDefault(); navigate(target) }}>
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
      </div>
    </div>
  )
}
