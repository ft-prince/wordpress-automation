// ⌘K: jump to a page, run an automation, or start a crawl / sync from anywhere.
import { useEffect, useRef, useState } from 'react'
import { api } from '../api'

export default function Palette({ nav, onNavigate, notify, onClose }) {
  const [q, setQ] = useState('')
  const [jobs, setJobs] = useState([])
  const [idx, setIdx] = useState(0)
  const input = useRef(null)
  useEffect(() => { input.current?.focus(); api.jobs().then(setJobs).catch(() => {}) }, [])
  const items = [
    ...nav.map(([key, label]) => ({ label: `Go to ${label}`, hint: 'page', run: () => onNavigate(key) })),
    ...jobs.map((j) => ({ label: `Run ${j.name}`, hint: j.status === 'running' ? 'running' : 'automation',
      run: () => api.run(j.id).then(() => notify(`${j.name} started`)).catch((e) => notify(e.message, true)) })),
    { label: 'New brief', hint: 'content', run: () => onNavigate('content') },
    { label: 'Crawl site now', hint: 'seo', run: () => api.startCrawl().then(() => notify('crawl started')).catch((e) => notify(e.message, true)) },
    { label: 'Sync Google now', hint: 'performance', run: () => api.googleSync().then((r) => notify(r.started ? 'sync started' : r.detail)).catch((e) => notify(e.message, true)) },
  ]
  const hits = items.filter((i) => i.label.toLowerCase().includes(q.toLowerCase())).slice(0, 12)
  const pick = (i) => { onClose(); i?.run() }
  const onKey = (e) => {
    if (e.key === 'Escape') onClose()
    if (e.key === 'ArrowDown') { e.preventDefault(); setIdx((i) => Math.min(i + 1, hits.length - 1)) }
    if (e.key === 'ArrowUp') { e.preventDefault(); setIdx((i) => Math.max(i - 1, 0)) }
    if (e.key === 'Enter') pick(hits[idx])
  }
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 p-6 pt-24 max-md:p-2 max-md:pt-12" onClick={onClose}>
      <div className="w-full max-w-lg rounded-xl border border-edge bg-panel shadow-2xl" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Command palette">
        <input ref={input} value={q} onChange={(e) => { setQ(e.target.value); setIdx(0) }} onKeyDown={onKey} placeholder="Jump to a page, run an automation…"
          className="w-full border-b border-edge bg-transparent px-4 py-3 text-sm outline-none" />
        <ul className="max-h-80 overflow-y-auto p-1">
          {hits.map((i, n) => (
            <li key={i.label}><button onMouseEnter={() => setIdx(n)} onClick={() => pick(i)}
              className={`flex w-full items-center rounded-lg px-3 py-2 text-left text-sm ${n === idx ? 'bg-edge/60 text-ink' : 'text-dim'}`}>
              {i.label}<span className="ml-auto mono text-[10px] uppercase text-dim">{i.hint}</span></button></li>
          ))}
          {hits.length === 0 && <li className="px-3 py-3 text-sm text-dim">Nothing matches.</li>}
        </ul>
      </div>
    </div>
  )
}
