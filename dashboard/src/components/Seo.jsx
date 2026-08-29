// SEO audit page: every post scored, issues listed, suggested fixes approved with one click.
import { useEffect, useState } from 'react'
import { api, site } from '../api'
import { Badge, btnGhost, btnPrimary, Empty, Spinner } from './bits'
import ItemEditor from './ItemEditor'

const scoreTone = (s) => (s >= 80 ? 'var(--color-ok)' : s >= 50 ? 'var(--color-accent)' : 'var(--color-bad)')

const seoFetch = (force = false) =>
  fetch(`/api/seo/audit?force=${force}${site.current() ? `&site=${site.current()}` : ''}`, { headers: { 'X-Auth-Token': localStorage.getItem('dash_token') || '' } })
    .then((r) => (r.ok ? r.json() : r.json().then((b) => Promise.reject(new Error(b.detail)))))

const applyFix = (item, fix) =>
  fetch(`/api/seo/items/${item.id}/apply${site.current() ? `?site=${site.current()}` : ''}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Auth-Token': localStorage.getItem('dash_token') || '' },
    body: JSON.stringify({ base: item.base, field: fix.field, value: fix.value }),
  }).then((r) => (r.ok ? r.json() : r.json().then((b) => Promise.reject(new Error(b.detail)))))

function Issue({ item, issue, notify, reload, onEdit }) {
  const [busy, setBusy] = useState(false)
  const [suggested, setSuggested] = useState(issue.fix?.value || null)
  const suggest = () => {
    setBusy(true)
    fetch(`/api/seo/items/${item.id}/suggest${site.current() ? `?site=${site.current()}` : ''}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Auth-Token': localStorage.getItem('dash_token') || '' },
      body: JSON.stringify({ base: item.base }),
    }).then((r) => (r.ok ? r.json() : r.json().then((b) => Promise.reject(new Error(b.detail)))))
      .then((d) => setSuggested(d.value))
      .catch((e) => notify(e.message, true))
      .finally(() => setBusy(false))
  }
  const approve = () => {
    setBusy(true)
    applyFix(item, { ...issue.fix, value: suggested })
      .then(() => { notify(`Applied: ${issue.fix.label}`); reload() })
      .catch((e) => notify(e.message, true))
      .finally(() => setBusy(false))
  }
  return (
    <div className="rounded-lg border border-edge bg-base p-3">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 text-sm" style={{ color: issue.fix ? 'var(--color-accent)' : 'var(--color-dim)' }}>
          {issue.fix ? '⚡' : '•'}
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium">{issue.label}</p>
          <p className="text-xs text-dim">{issue.detail}</p>
          {suggested && (
            <p className="mt-1.5 rounded bg-edge/40 px-2 py-1.5 text-xs mono" style={{ color: 'var(--color-ok)' }}>
              suggested: {suggested}
            </p>
          )}
        </div>
        {issue.fix ? (
          suggested ? (
            <button className={btnPrimary} disabled={busy} onClick={approve}>
              {busy ? 'Applying…' : 'Approve'}
            </button>
          ) : (
            <button className={btnPrimary} disabled={busy} onClick={suggest}>
              {busy ? 'Writing…' : 'Suggest a fix'}
            </button>
          )
        ) : (
          <button className={btnGhost} onClick={onEdit}>
            {item.type === 'post' ? 'Edit post' : 'Edit page'}
          </button>
        )}
      </div>
    </div>
  )
}

export default function Seo({ notify, onNavigate }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  const [running, setRunning] = useState(false)
  const [editItem, setEditItem] = useState(null)
  const load = (force = false) => {
    if (force) setRunning(true)
    return seoFetch(force)
      .then((d) => { setData(d); setError(null) })
      .catch((e) => setError(e.message))
      .finally(() => setRunning(false))
  }
  useEffect(() => { load() }, [])

  if (error) return (
    <div className="rounded-lg border px-4 py-3 text-sm" style={{ borderColor: 'var(--color-bad)', color: 'var(--color-bad)' }}>
      audit failed: {error} — <button className="underline" onClick={() => load(true)}>retry</button>
    </div>
  )
  if (!data) return <Spinner label={running ? 'Checking every page and post on your site…' : 'Loading saved results…'} />

  const { summary, results, generated_at } = data

  if (!summary) return (
    <div className="max-w-xl rounded-xl border border-edge bg-panel p-8 text-center">
      <p className="text-sm text-dim">No SEO check has been run for this site yet.</p>
      <button className={`${btnPrimary} mt-4`} onClick={() => { setData(null); load(true) }}>
        Run first audit
      </button>
      <p className="mt-2 text-xs text-dim">Takes about ten seconds. Results are saved, so this page loads instantly afterwards.</p>
    </div>
  )
  return (
    <div className="max-w-3xl space-y-5">
      <div className="flex items-center gap-4">
        <div className="grid flex-1 grid-cols-2 gap-3 md:grid-cols-4">
          {[['avg score', `${summary.avg_score}%`, scoreTone(summary.avg_score)],
            ['items audited', summary.items],
            ['with issues', summary.with_issues, summary.with_issues ? 'var(--color-accent)' : undefined],
            ['one-click fixable', summary.fixable, summary.fixable ? 'var(--color-accent)' : undefined],
          ].map(([label, value, tone]) => (
            <div key={label} className="rounded-xl border border-edge bg-panel px-4 py-3">
              <div className="text-2xl font-bold mono" style={tone ? { color: tone } : undefined}>{value}</div>
              <div className="mt-0.5 text-xs uppercase tracking-widest text-dim">{label}</div>
            </div>
          ))}
        </div>
        <div className="text-right">
          <button className={btnGhost} onClick={() => { setData(null); load(true) }}>Re-check</button>
          {generated_at && <p className="mt-1 text-xs text-dim mono">checked {new Date(generated_at).toLocaleString()}</p>}
        </div>
      </div>

      {results.length === 0 ? <Empty quip="Nothing to audit yet." /> : results.map((r) => (
        <section key={`${r.base}-${r.id}`} className="rounded-xl border border-edge bg-panel p-4">
          <div className="mb-1 flex items-center gap-3">
            <span className="text-lg font-bold mono" style={{ color: scoreTone(r.score) }}>{r.score}%</span>
            <a href={r.link} target="_blank" rel="noreferrer" className="min-w-0 flex-1 truncate font-medium underline-offset-2 hover:underline">
              {r.title}
            </a>
            <span className="rounded-full border border-edge px-2 py-0.5 text-xs text-dim">{r.type}</span>
            <Badge status={r.status} />
          </div>
          <div className="mb-3 h-1.5 overflow-hidden rounded-full bg-edge">
            <div className="h-full rounded-full transition-all duration-300" style={{ width: `${r.score}%`, background: scoreTone(r.score) }} />
          </div>
          {r.issues.length === 0 ? (
            <p className="text-sm" style={{ color: 'var(--color-ok)' }}>✓ all checks pass</p>
          ) : (
            <div className="space-y-2">
              {r.issues.map((issue) => (
                <Issue key={issue.code} item={r} issue={issue} notify={notify}
                  reload={() => load(false)}
                  onEdit={() => {
                    if (r.type === 'post') { onNavigate('posts', r.id); return }
                    setEditItem({ base: r.base, id: r.id })
                  }} />
              ))}
            </div>
          )}
        </section>
      ))}

      {editItem && (
        <ItemEditor base={editItem.base} itemId={editItem.id} notify={notify}
          onClose={() => setEditItem(null)} onSaved={() => load(false)} />
      )}
    </div>
  )
}
