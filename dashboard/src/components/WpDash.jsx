// WordPress content sections: connection, alerts, pipeline, published, upcoming, performance.
import { useEffect, useState } from 'react'
import { api } from '../api'
import { Empty, fmtTime } from './bits'
import SeoChip from './SeoChip'

const wpApi = {
  health: () => api.health(),
  alerts: () => api.alerts(),
  pipeline: () => api.pipeline(),
  posts: (status, limit = 10) => api.posts({ status, limit }),
  setStatus: (id, status) => api.updatePost(id, { status }),
}

function Section({ title, right, children }) {
  return (
    <section className="rounded-xl border border-edge bg-panel p-5">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-sm uppercase tracking-widest text-dim">{title}</h2>
        {right}
      </div>
      {children}
    </section>
  )
}

const okDot = (ok) => (
  <span className="inline-flex items-center gap-1.5 text-xs mono" style={{ color: ok ? 'var(--color-ok)' : 'var(--color-bad)' }}>
    <span className="h-2 w-2 rounded-full" style={{ background: ok ? 'var(--color-ok)' : 'var(--color-bad)' }} />
    {ok ? 'ok' : 'down'}
  </span>
)

export function AlertsBar() {
  const [alerts, setAlerts] = useState([])
  useEffect(() => {
    const load = () => wpApi.alerts().then(setAlerts).catch(() => {})
    load()
    const t = setInterval(load, 8000)
    return () => clearInterval(t)
  }, [])
  if (alerts.length === 0) return null
  const tone = { critical: 'var(--color-bad)', error: 'var(--color-bad)', warn: 'var(--color-accent)' }
  return (
    <div className="space-y-1.5">
      {alerts.map((a, i) => (
        <div key={i} className="log-line flex items-center gap-2 rounded-lg border bg-panel px-4 py-2 text-sm" style={{ borderColor: tone[a.level] }}>
          <span className="text-xs uppercase mono" style={{ color: tone[a.level] }}>{a.level}</span>
          {a.text}
        </div>
      ))}
    </div>
  )
}

export function ConnectionHealth() {
  const [h, setH] = useState(null)
  useEffect(() => {
    const load = () => wpApi.health().then(setH).catch(() => {})
    load()
    const t = setInterval(load, 10000)
    return () => clearInterval(t)
  }, [])
  if (!h) return null
  const wp = h.wp || {}
  const cells = [
    ['WordPress API', okDot(wp.connected), wp.connected ? `${wp.latency_ms}ms` : wp.error],
    ['Site', null, wp.site?.replace('https://', '')],
    ['Auth', okDot(wp.connected), wp.connected ? `${wp.user} · ${wp.auth}` : '—'],
    ['Scheduler', okDot(h.scheduler_running), h.scheduler_running ? 'running' : 'stopped'],
    ['Database', okDot(h.db_ok), h.db_ok ? 'sqlite · wal' : 'error'],
    ['Workers', null, `${h.workers_active ?? '—'} active`],
    ['Last sync', null, wp.last_ok ? fmtTime(wp.last_ok) : 'never'],
    ['Last success', null, fmtTime(h.last_successful_run)],
  ]
  return (
    <Section title="Connection & system health">
      <div className="grid grid-cols-2 gap-x-6 gap-y-3 md:grid-cols-4">
        {cells.map(([label, dot, value]) => (
          <div key={label}>
            <div className="flex items-center gap-2 text-xs text-dim">{label} {dot}</div>
            <div className="mt-0.5 text-sm mono truncate">{value}</div>
          </div>
        ))}
      </div>
    </Section>
  )
}

const STAGES = [
  ['idea', 'Idea'], ['generated', 'Generated'], ['review', 'Review'],
  ['scheduled', 'Scheduled'], ['published', 'Published'],
]

export function Pipeline({ onNavigate }) {
  const [p, setP] = useState(null)
  useEffect(() => {
    const load = () => wpApi.pipeline().then(setP).catch(() => {})
    load()
    const t = setInterval(load, 15000)
    return () => clearInterval(t)
  }, [])
  if (!p) return null
  const count = (k) => (k === 'published' ? p.published_total : (p[k] || []).length)
  return (
    <Section title="Content pipeline">
      <div className="flex items-center gap-2 overflow-x-auto">
        {STAGES.map(([key, label], i) => (
          <div key={key} className="flex items-center gap-2">
            <div className={`min-w-24 rounded-lg border border-edge bg-base px-4 py-3 text-center ${key === 'idea' && onNavigate ? 'cursor-pointer hover:border-accent' : ''}`}
              onClick={key === 'idea' && onNavigate ? () => onNavigate('topics') : undefined}
              role={key === 'idea' && onNavigate ? 'button' : undefined}>
              <div className="text-2xl font-bold mono" style={{ color: count(key) ? 'var(--color-accent)' : 'var(--color-dim)' }}>
                {count(key)}
              </div>
              <div className="text-xs text-dim">{label}</div>
            </div>
            {i < STAGES.length - 1 && <span className="text-dim">→</span>}
          </div>
        ))}
      </div>
      {(p.idea || []).length > 0 && (
        <p className="mt-3 text-xs text-dim mono truncate">next idea: {p.idea[0]}</p>
      )}
    </Section>
  )
}

function Thumb({ src }) {
  return src ? (
    <img src={src} alt="" className="h-9 w-14 rounded object-cover" />
  ) : (
    <span className="flex h-9 w-14 items-center justify-center rounded bg-edge text-dim" aria-label="no featured image">
      <svg viewBox="0 0 24 24" className="h-4 w-4"><path d="M4 5h16v14H4zm3 10 3-4 2 2 3-5 5 7" fill="none" stroke="currentColor" strokeWidth="1.5" /></svg>
    </span>
  )
}

function PostActions({ post, notify, reload }) {
  const move = (status, label) =>
    wpApi.setStatus(post.id, status)
      .then(() => { notify(`"${post.title}": ${label}`); reload() })
      .catch((e) => notify(e.message, true))
  const btn = 'rounded border border-edge px-2 py-1 text-xs hover:border-accent'
  return (
    <span className="flex flex-wrap gap-1.5">
      {post.status !== 'publish' && (
        <button className={btn} onClick={() => confirm(`Publish "${post.title}" live now?`) && move('publish', 'published')}>Publish</button>
      )}
      {post.status === 'draft' && <button className={btn} onClick={() => move('pending', 'sent to review')}>→ Review</button>}
      {post.status === 'pending' && <button className={btn} onClick={() => move('draft', 'back to draft')}>Reject</button>}
      <a className={btn} href={post.status === 'publish' ? post.link : post.preview_url} target="_blank" rel="noreferrer">
        {post.status === 'publish' ? 'View' : 'Preview'}
      </a>
      <a className={btn} href={post.edit_url} target="_blank" rel="noreferrer">Edit</a>
    </span>
  )
}

export function PublishedPosts({ notify }) {
  const [posts, setPosts] = useState(null)
  const load = () => wpApi.posts('publish').then(setPosts).catch(() => setPosts([]))
  useEffect(() => { load(); const t = setInterval(load, 30000); return () => clearInterval(t) }, [])
  return (
    <Section title="Published posts">
      {!posts ? <p className="text-dim text-sm">loading…</p> : posts.length === 0 ? (
        <Empty quip="Nothing published yet." />
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wider text-dim">
              {['', 'title', 'published', 'author', 'category', 'tags', 'actions'].map((h, i) => <th key={i} className="pb-2 pr-3 font-normal">{h}</th>)}
            </tr>
          </thead>
          <tbody>
            {posts.map((p) => (
              <tr key={p.id} className="border-t border-edge/50">
                <td className="py-2 pr-3"><Thumb src={p.featured_image} /></td>
                <td className="py-2 pr-3">
                  <a href={p.link} target="_blank" rel="noreferrer" className="font-medium underline-offset-2 hover:underline">{p.title}</a>
                  <span className="ml-2"><SeoChip seo={p.seo} /></span>
                </td>
                <td className="py-2 pr-3 mono text-dim">{fmtTime(p.date_gmt + 'Z')}</td>
                <td className="py-2 pr-3 text-dim">{p.author}</td>
                <td className="py-2 pr-3 text-dim">{p.categories.join(', ') || '—'}</td>
                <td className="py-2 pr-3 text-dim">{p.tags.join(', ') || '—'}</td>
                <td className="py-2"><PostActions post={p} notify={notify} reload={load} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Section>
  )
}

function Countdown({ target }) {
  const [, tick] = useState(0)
  useEffect(() => { const t = setInterval(() => tick((n) => n + 1), 1000); return () => clearInterval(t) }, [])
  const ms = new Date(target + 'Z') - Date.now()
  if (ms <= 0) return <span style={{ color: 'var(--color-bad)' }}>overdue</span>
  const h = Math.floor(ms / 3.6e6), m = Math.floor((ms % 3.6e6) / 6e4), s = Math.floor((ms % 6e4) / 1e3)
  return <span className="mono" style={{ color: 'var(--color-accent)' }}>{h > 0 ? `${h}h ${m}m` : `${m}m ${s}s`}</span>
}

export function UpcomingPosts({ notify }) {
  const [queue, setQueue] = useState(null)
  const load = () =>
    Promise.all([wpApi.posts('future'), wpApi.posts('draft'), wpApi.posts('pending')])
      .then(([f, d, p]) => setQueue({ future: f, drafts: [...p, ...d] }))
      .catch(() => setQueue({ future: [], drafts: [] }))
  useEffect(() => { load(); const t = setInterval(load, 30000); return () => clearInterval(t) }, [])
  if (!queue) return null
  return (
    <Section title="Upcoming & awaiting approval">
      {queue.future.length === 0 && queue.drafts.length === 0 ? (
        <Empty quip="Nothing waiting to publish right now." />
      ) : (
        <div className="space-y-2">
          {queue.future.map((p) => (
            <div key={p.id} className="flex items-center gap-4 rounded-lg border border-edge bg-base px-4 py-2.5 text-sm">
              <Thumb src={p.featured_image} />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2"><span className="truncate font-medium">{p.title}</span><SeoChip seo={p.seo} /></div>
                <div className="text-xs text-dim mono">scheduled {fmtTime(p.date_gmt + 'Z')} · in <Countdown target={p.date_gmt} /></div>
              </div>
              <PostActions post={p} notify={notify} reload={load} />
            </div>
          ))}
          {queue.drafts.map((p) => (
            <div key={p.id} className="flex items-center gap-4 rounded-lg border border-edge bg-base px-4 py-2.5 text-sm">
              <Thumb src={p.featured_image} />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2"><span className="truncate font-medium">{p.title}</span><SeoChip seo={p.seo} /></div>
                <div className="text-xs text-dim mono">
                  {p.status === 'pending' ? 'waiting for approval' : 'draft, ready for your review'} · created {fmtTime(p.date_gmt + 'Z')}
                </div>
              </div>
              <PostActions post={p} notify={notify} reload={load} />
            </div>
          ))}
        </div>
      )}
    </Section>
  )
}

export function Performance() {
  // WP core exposes no view/click metrics. Honest empty state beats fake numbers.
  return (
    <Section title="Post performance">
      <div className="flex items-center gap-4 py-2 text-sm text-dim">
        <svg viewBox="0 0 48 32" className="h-10 w-14" aria-hidden="true">
          <path d="M4 26 14 18l8 4 10-10 8 6" fill="none" stroke="var(--color-dim)" strokeWidth="2" strokeDasharray="3 3" />
          <circle cx="40" cy="8" r="3" fill="none" stroke="var(--color-accent)" strokeWidth="1.5" />
        </svg>
        <p>
          WordPress core has no analytics API. Connect <span className="text-ink">Jetpack Stats</span> or{' '}
          <span className="text-ink">Google Analytics</span> and this panel lights up with views, clicks and engagement.
        </p>
      </div>
    </Section>
  )
}
