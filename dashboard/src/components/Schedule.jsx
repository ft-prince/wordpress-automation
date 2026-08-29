// Calendar-style list: upcoming posts + automation runs grouped by day, conflicts flagged.
import { useEffect, useState } from 'react'
import { api } from '../api'
import { Badge, btnGhost, Empty, fmtTime, humanCron, Spinner } from './bits'

export default function Schedule({ notify }) {
  const [items, setItems] = useState(null)

  const load = () =>
    Promise.all([api.posts({ status: 'future', limit: 50 }), api.jobs()])
      .then(([posts, jobs]) => {
        const events = [
          ...posts.map((p) => ({
            kind: 'post', ts: p.date_gmt + 'Z', label: p.title, status: 'future',
            overdue: new Date(p.date_gmt + 'Z') < new Date(), id: p.id, edit_url: p.edit_url,
          })),
          ...jobs.filter((j) => j.next_run).map((j) => ({
            kind: 'automation', ts: j.next_run, label: j.name, status: j.enabled === false ? 'paused' : 'scheduled',
            schedule: humanCron(j.schedule), id: j.id,
          })),
        ].sort((a, b) => a.ts.localeCompare(b.ts))
        // conflict = two events inside the same 5-minute window
        events.forEach((e, i) => {
          e.conflict = events.some((o, j) => j !== i && Math.abs(new Date(o.ts) - new Date(e.ts)) < 5 * 60 * 1000)
        })
        setItems(events)
      })
      .catch((e) => { notify(e.message, true); setItems([]) })

  useEffect(() => { load(); const t = setInterval(load, 30000); return () => clearInterval(t) }, [])

  if (items === null) return <Spinner label="loading schedule…" />
  if (items.length === 0) return <Empty quip="Nothing scheduled yet." />

  const byDay = items.reduce((acc, e) => {
    const day = e.ts.slice(0, 10)
    ;(acc[day] = acc[day] || []).push(e)
    return acc
  }, {})

  return (
    <div className="max-w-3xl space-y-6">
      {Object.entries(byDay).map(([day, events]) => (
        <section key={day}>
          <h2 className="mb-2 text-sm uppercase tracking-widest text-dim">
            {new Date(day).toLocaleDateString(undefined, { weekday: 'long', month: 'short', day: 'numeric' })}
          </h2>
          <div className="space-y-2">
            {events.map((e, i) => (
              <div key={i} className="flex items-center gap-4 rounded-lg border bg-panel px-4 py-3 text-sm"
                style={{ borderColor: e.overdue ? 'var(--color-bad)' : e.conflict ? 'var(--color-accent)' : 'var(--color-edge)' }}>
                <span className="mono text-dim w-16">{new Date(e.ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                <span className="rounded-full border border-edge px-2 py-0.5 text-xs text-dim">{e.kind}</span>
                <span className="min-w-0 flex-1 truncate font-medium">{e.label}</span>
                {e.schedule && <span className="text-xs text-dim mono">{e.schedule}</span>}
                {e.overdue && <span className="text-xs mono" style={{ color: 'var(--color-bad)' }}>⚠ missed</span>}
                {e.conflict && !e.overdue && <span className="text-xs mono" style={{ color: 'var(--color-accent)' }}>⚠ overlaps</span>}
                <Badge status={e.status === 'scheduled' ? 'future' : e.status} />
                {e.kind === 'post' && e.overdue && (
                  <button className={btnGhost} onClick={() =>
                    api.updatePost(e.id, { status: 'publish' }).then(() => { notify('published'); load() }).catch((err) => notify(err.message, true))
                  }>Publish now</button>
                )}
              </div>
            ))}
          </div>
        </section>
      ))}
    </div>
  )
}
