import { useEffect, useState } from 'react'
import { api } from '../api'
import { Badge, Dot, Empty, FailureArt, fmtMs, fmtTime, Spinner } from './bits'
import { AlertsBar, Performance, Pipeline, PublishedPosts, UpcomingPosts } from './WpDash'

function Stat({ label, value, tone, onClick }) {
  const Tag = onClick ? 'button' : 'div'
  return (
    <Tag onClick={onClick} className={`rounded-xl border border-edge bg-panel px-4 py-3.5 text-left ${onClick ? 'hover:border-accent transition-colors duration-200' : ''}`}>
      <div className="text-3xl font-bold mono" style={tone ? { color: tone } : undefined}>{value ?? '—'}</div>
      <div className="mt-1 text-xs uppercase tracking-widest text-dim">{label}</div>
    </Tag>
  )
}

function RunningNow({ jobs }) {
  const running = jobs.filter((j) => j.status === 'running')
  if (running.length === 0) return null
  return (
    <div className="rounded-xl border bg-panel p-5" style={{ borderColor: 'var(--color-run)' }}>
      <h2 className="mb-3 text-sm uppercase tracking-widest" style={{ color: 'var(--color-run)' }}>Running now</h2>
      {running.map((j) => (
        <div key={j.id} className="flex items-center gap-4 text-sm">
          <Badge status="running" />
          <span className="font-medium">{j.name}</span>
          <span className="mono text-xs text-dim">started {fmtTime(j.last_run?.started_at)}</span>
          {j.current_step && <span className="mono text-xs text-dim truncate flex-1">→ {j.current_step}</span>}
        </div>
      ))}
    </div>
  )
}

function Heatmap({ cells, jobs }) {
  const days = [...Array(7)].map((_, i) => { const d = new Date(); d.setDate(d.getDate() - (6 - i)); return d.toISOString().slice(0, 10) })
  const lookup = Object.fromEntries(cells.map((c) => [`${c.job_id}|${c.day}`, c]))
  if (jobs.length === 0) return null
  return (
    <div className="rounded-xl border border-edge bg-panel p-5">
      <h2 className="mb-4 text-sm uppercase tracking-widest text-dim">7-day outcomes</h2>
      <table className="w-full">
        <thead><tr><th className="pb-2 text-left text-xs text-dim font-normal">automation</th>
          {days.map((d) => <th key={d} className="pb-2 text-xs text-dim mono font-normal">{d.slice(5)}</th>)}</tr></thead>
        <tbody>
          {jobs.map((j) => (
            <tr key={j.id}><td className="py-1 pr-3 text-sm">{j.name}</td>
              {days.map((d) => {
                const c = lookup[`${j.id}|${d}`]
                const bg = !c ? 'var(--color-edge)' : c.bad > 0 ? 'var(--color-bad)' : 'var(--color-ok)'
                return <td key={d} className="py-1 text-center">
                  <span title={`${d}: ${c ? `${c.ok} ok / ${c.bad} failed` : 'no runs'}`} className="inline-block h-5 w-5 rounded" style={{ background: bg, opacity: c ? 1 : 0.4 }} />
                </td>
              })}</tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function Overview({ onNavigate, notify }) {
  const [stats, setStats] = useState(null)
  const [metrics, setMetrics] = useState(null)
  const [jobs, setJobs] = useState([])
  const [feed, setFeed] = useState([])
  const [health, setHealth] = useState(null)

  useEffect(() => {
    const load = () =>
      Promise.all([api.overview(), api.metrics(), api.jobs(), api.runs({ limit: 8 }), api.health()])
        .then(([o, m, j, r, h]) => { setStats(o); setMetrics(m); setJobs(j); setFeed(r); setHealth(h) })
        .catch(() => {})
    load()
    const t = setInterval(load, 5000)
    return () => clearInterval(t)
  }, [])

  if (!stats) return <Spinner label="loading dashboard…" />

  const attention = jobs.filter((j) => ['failed', 'timeout'].includes(j.status) || j.enabled === false)
  const nextRuns = jobs.map((j) => j.next_run).filter(Boolean).sort()
  const wp = health?.wp || {}

  return (
    <div className="space-y-5">
      <AlertsBar />

      {/* connection strip */}
      <div className="flex flex-wrap items-center gap-x-6 gap-y-1 rounded-xl border border-edge bg-panel px-4 py-2.5 text-xs mono text-dim">
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full" style={{ background: wp.connected ? 'var(--color-ok)' : 'var(--color-bad)' }} />
          WordPress {wp.connected ? `connected · ${wp.latency_ms}ms` : 'DISCONNECTED'}
        </span>
        <span>{wp.site?.replace('https://', '')}</span>
        <span>auth: {wp.user || '—'}</span>
        <span>last sync: {wp.last_ok ? fmtTime(wp.last_ok) : 'never'}</span>
        <span>last success: {fmtTime(health?.last_successful_run)}</span>
        <span className="ml-auto">next automation: {nextRuns[0] ? fmtTime(nextRuns[0]) : '—'}</span>
      </div>

      {/* stat tiles */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
        <Stat label="total posts" value={stats.posts_total} onClick={() => onNavigate('posts')} />
        <Stat label="published today" value={stats.published_today} tone="var(--color-ok)" onClick={() => onNavigate('posts')} />
        <Stat label="this week" value={stats.published_week} tone="var(--color-ok)" onClick={() => onNavigate('posts')} />
        <Stat label="scheduled" value={stats.scheduled} tone="var(--color-run)" onClick={() => onNavigate('schedule')} />
        <Stat label="drafts" value={stats.drafts} onClick={() => onNavigate('posts')} />
        <Stat label="approvals" value={stats.pending_approval} tone={stats.pending_approval ? 'var(--color-accent)' : undefined} onClick={() => onNavigate('posts')} />
        <Stat label="running" value={stats.running_now} tone="var(--color-run)" onClick={() => onNavigate('logs')} />
        <Stat label="failed 24h" value={stats.failed_24h} tone={stats.failed_24h ? 'var(--color-bad)' : undefined} onClick={() => onNavigate('logs')} />
        <Stat label="technical score" value={stats.seo?.technical_score != null ? `${stats.seo.technical_score}%` : null} tone={stats.seo?.technical_score >= 80 ? 'var(--color-ok)' : stats.seo?.technical_score != null ? 'var(--color-accent)' : undefined} onClick={() => onNavigate('seo')} />
        <Stat label="QA pass rate" value={stats.seo?.qa_pass_rate != null ? `${stats.seo.qa_pass_rate}%` : null} onClick={() => onNavigate('content')} />
        <Stat label="pending changes" value={stats.seo?.pending_changes} tone={stats.seo?.pending_changes ? 'var(--color-accent)' : undefined} onClick={() => onNavigate('content')} />
        <Stat label="clicks 28d" value={stats.seo?.gsc_clicks_28d} tone="var(--color-run)" onClick={() => onNavigate('performance')} />
      </div>

      <RunningNow jobs={jobs} />

      {attention.length > 0 && (
        <div className="flex items-center gap-4 rounded-xl border bg-panel p-4" style={{ borderColor: 'var(--color-bad)' }}>
          <FailureArt />
          <div className="text-sm">
            <h2 className="font-medium" style={{ color: 'var(--color-bad)' }}>Needs attention</h2>
            {attention.map((j) => (
              <div key={j.id} className="mt-1 flex items-center gap-3">
                <button onClick={() => onNavigate('automations', j.id)} className="underline-offset-2 hover:underline">
                  {j.name} — {j.enabled === false ? 'disabled' : `${j.status}: ${j.last_run?.error || 'unknown'}`}
                </button>
                {j.last_run && ['failed', 'timeout'].includes(j.status) && (
                  <button className="rounded border border-edge px-2 py-0.5 text-xs hover:border-accent"
                    onClick={() => api.retry(j.last_run.id).then(() => notify('retry started')).catch((e) => notify(e.message, true))}>
                    Retry
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      <Pipeline onNavigate={onNavigate} />
      <UpcomingPosts notify={notify} />
      <div className="grid gap-5 lg:grid-cols-2">
        <Heatmap cells={metrics?.heatmap || []} jobs={jobs} />
        <div className="rounded-xl border border-edge bg-panel p-5">
          <h2 className="mb-3 text-sm uppercase tracking-widest text-dim">Recent activity</h2>
          {feed.length === 0 ? <Empty quip="No activity yet." /> : (
            <ul className="space-y-1.5">
              {feed.map((r) => (
                <li key={r.id} className="flex items-center gap-3 text-sm mono">
                  <Dot status={r.status} />
                  <span className="text-dim">#{r.id}</span>
                  <span>{r.job_id}</span>
                  <span className="text-dim text-xs">{fmtTime(r.started_at)}</span>
                  <span className="text-dim text-xs">{fmtMs(r.duration_ms)}</span>
                  {r.dry_run === 1 && <span className="text-xs text-dim">(dry)</span>}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
      <PublishedPosts notify={notify} />
      <Performance />
    </div>
  )
}
