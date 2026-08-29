// Topic engine UI: AI-discovered suggestions → approve into an ordered writing queue.
import { useEffect, useState } from 'react'
import { auth, site } from '../api'
import { btnGhost, btnPrimary, Empty, field, Spinner } from './bits'

const call = (path, method = 'GET', body) =>
  fetch(`${path}${path.includes('?') ? '&' : '?'}${site.current() ? `site=${site.current()}` : ''}`, {
    method,
    headers: { 'Content-Type': 'application/json', 'X-Auth-Token': auth.token() },
    body: body === undefined ? undefined : JSON.stringify(body),
  }).then((r) => (r.ok ? r.json() : r.json().then((b) => Promise.reject(new Error(b.detail)))))

const SOURCE_STYLE = {
  'site-gap': ['coverage gap', 'var(--color-accent)'],
  serp: ['ranking now', 'var(--color-run)'],
  trending: ['trending', 'var(--color-ok)'],
  cluster: ['link cluster', 'var(--color-run)'],
  manual: ['manual', 'var(--color-dim)'],
}

function SourceChip({ source }) {
  const [label, color] = SOURCE_STYLE[source] || SOURCE_STYLE.manual
  return (
    <span className="rounded-full px-2 py-0.5 text-xs mono"
      style={{ color, border: `1px solid color-mix(in srgb, ${color} 40%, transparent)` }}>
      {label}
    </span>
  )
}

function Relevance({ value }) {
  const tone = value >= 80 ? 'var(--color-ok)' : value >= 60 ? 'var(--color-accent)' : 'var(--color-dim)'
  return (
    <span className="flex items-center gap-1.5" title={`relevance ${value}/100`}>
      <span className="mono text-sm font-bold" style={{ color: tone }}>{value}</span>
      <span className="h-1.5 w-14 overflow-hidden rounded-full bg-edge">
        <span className="block h-full rounded-full" style={{ width: `${value}%`, background: tone }} />
      </span>
    </span>
  )
}

export default function Topics({ notify }) {
  const [data, setData] = useState(null)
  const [finding, setFinding] = useState(false)
  const [newTitle, setNewTitle] = useState('')
  const [writing, setWriting] = useState(false)

  const load = () => call('/api/topics').then(setData).catch((e) => notify(e.message, true))
  useEffect(() => { load() }, [])

  const act = (promise, msg) => promise.then(() => { msg && notify(msg); load() }).catch((e) => notify(e.message, true))

  const discover = () => {
    setFinding(true)
    call('/api/topics/discover', 'POST')
      .then((d) => { notify(`${d.found} new topic${d.found === 1 ? '' : 's'} suggested`); load() })
      .catch((e) => notify(e.message, true))
      .finally(() => setFinding(false))
  }

  const writeNow = () => {
    setWriting(true)
    call('/api/jobs/publish-blog/run', 'POST', { dry_run: false })
      .then(() => notify('Writing now. Follow along in Logs; the draft will show up in Posts'))
      .catch((e) => notify(e.message, true))
      .finally(() => setWriting(false))
  }

  if (!data) return <Spinner label="loading topics…" />
  const { suggested, approved, written } = data

  return (
    <div className="max-w-3xl space-y-6">
      {/* queue */}
      <section>
        <div className="mb-2 flex items-center gap-3">
          <h2 className="text-sm uppercase tracking-widest text-dim">Writing queue</h2>
          <span className="mono text-xs" style={{ color: approved.length < 2 ? 'var(--color-bad)' : 'var(--color-dim)' }}>
            {approved.length} queued{approved.length < 2 && ', running low'}
          </span>
          {approved.length > 0 && (
            <button className={`${btnPrimary} ml-auto`} onClick={writeNow} disabled={writing}>
              {writing ? 'Started…' : '▸ Write next now'}
            </button>
          )}
        </div>
        {approved.length === 0 ? (
          <Empty quip="The queue is empty. Approve a suggestion below to get started." />
        ) : (
          <div className="space-y-1.5">
            {approved.map((t, i) => (
              <div key={t.id} className="flex items-center gap-3 rounded-lg border border-edge bg-panel px-3 py-2.5 text-sm">
                <span className="mono text-dim w-5">{i + 1}.</span>
                <span className="min-w-0 flex-1 truncate font-medium" title={t.why}>{t.title}</span>
                <SourceChip source={t.source} />
                {t.category && <span className="text-xs text-dim">{t.category}</span>}
                <span className="flex gap-1">
                  <button className={btnGhost} disabled={i === 0} aria-label="Move up"
                    onClick={() => act(call(`/api/topics/${t.id}/move?direction=up`, 'POST'))}>↑</button>
                  <button className={btnGhost} disabled={i === approved.length - 1} aria-label="Move down"
                    onClick={() => act(call(`/api/topics/${t.id}/move?direction=down`, 'POST'))}>↓</button>
                  <button className={btnGhost} onClick={() => act(call(`/api/topics/${t.id}`, 'PATCH', { status: 'suggested' }), 'Moved back to suggestions')}>Unqueue</button>
                </span>
              </div>
            ))}
          </div>
        )}
        <form className="mt-2 flex gap-2" onSubmit={(e) => {
          e.preventDefault()
          if (!newTitle.trim()) return
          act(call('/api/topics', 'POST', { title: newTitle.trim(), status: 'approved' }), 'topic queued')
          setNewTitle('')
        }}>
          <input className={field} placeholder="Type a topic to add it to the queue"
            value={newTitle} onChange={(e) => setNewTitle(e.target.value)} />
          <button type="submit" className={btnGhost} disabled={!newTitle.trim()}>Add</button>
        </form>
      </section>

      {/* suggestions */}
      <section>
        <div className="mb-2 flex items-center gap-3">
          <h2 className="text-sm uppercase tracking-widest text-dim">Suggested topics</h2>
          <span className="mono text-xs text-dim">{suggested.length}</span>
          <button className={`${btnPrimary} ml-auto`} onClick={discover} disabled={finding}>
            {finding ? 'Looking for topics…' : 'Find topics'}
          </button>
        </div>
        {suggested.length === 0 ? (
          <Empty quip={`No suggestions yet. Click "Find topics" and we'll look for some.`} />
        ) : (
          <div className="space-y-2">
            {suggested.map((t) => (
              <div key={t.id} className="rounded-xl border border-edge bg-panel p-4">
                <div className="flex items-center gap-3">
                  <Relevance value={t.relevance} />
                  <span className="min-w-0 flex-1 truncate font-medium">{t.title}</span>
                  <SourceChip source={t.source} />
                  {t.category && <span className="rounded-full border border-edge px-2 py-0.5 text-xs text-dim">{t.category}</span>}
                </div>
                {t.why && <p className="mt-1.5 text-xs text-dim">{t.why}</p>}
                <div className="mt-2 flex gap-2">
                  <button className={btnPrimary} onClick={() => act(call(`/api/topics/${t.id}`, 'PATCH', { status: 'approved' }), 'Added to the writing queue')}>
                    Approve → queue
                  </button>
                  <button className={btnGhost} onClick={() => act(call(`/api/topics/${t.id}`, 'PATCH', { status: 'rejected' }), "Rejected. We won't suggest this one again")}>
                    Reject
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* history */}
      {written.length > 0 && (
        <section>
          <h2 className="mb-2 text-sm uppercase tracking-widest text-dim">Already written</h2>
          <ul className="space-y-1 text-sm text-dim">
            {written.map((t) => (
              <li key={t.id} className="flex items-center gap-2">
                <span style={{ color: 'var(--color-ok)' }}>✓</span>
                <span className="truncate">{t.title}</span>
                {t.post_id && <span className="mono text-xs">→ post #{t.post_id}</span>}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
