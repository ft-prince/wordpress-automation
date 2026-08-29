import { useEffect, useState } from 'react'
import { api } from '../api'
import { Badge, btnGhost, btnPrimary, Empty, field, fmtMs, fmtTime, humanCron, Modal, PolicyField, ScheduleField, Spinner, Tag } from './bits'

function CreateJob({ notify, onClose, onCreated }) {
  const [form, setForm] = useState({ id: '', name: '', entrypoint: 'blog.py', schedule: 'manual', timeout_seconds: 300, description: '', policy: 'draft' })
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }))
  const save = () => {
    const { policy, ...rest } = form
    const payload = { ...rest, timeout_seconds: Number(form.timeout_seconds) }
    return api.createJob(payload)
      .then((j) => (form.entrypoint.includes('blog') ? api.patch(j.id, { args: { policy } }) : j))
      .then((j) => { notify(`automation "${j.name || form.name}" created`); onCreated() })
      .catch((e) => notify(e.message, true))
  }
  return (
    <Modal title="New automation" onClose={onClose}>
      <div className="space-y-3">
        <label className="block text-sm"><span className="text-dim">ID (lowercase, dashes)</span>
          <input className={`${field} mono`} value={form.id} onChange={(e) => set('id', e.target.value)} placeholder="my-automation" /></label>
        <label className="block text-sm"><span className="text-dim">Name</span>
          <input className={field} value={form.name} onChange={(e) => set('name', e.target.value)} /></label>
        <label className="block text-sm"><span className="text-dim">Script (entrypoint, relative to repo)</span>
          <input className={`${field} mono`} value={form.entrypoint} onChange={(e) => set('entrypoint', e.target.value)} /></label>
        <div className="block text-sm"><span className="text-dim">Schedule</span>
          <ScheduleField value={form.schedule} onChange={(v) => set('schedule', v)} />
        </div>
        {form.entrypoint.includes('blog') && (
          <div className="block text-sm"><span className="text-dim">Publish policy</span>
            <PolicyField value={form.policy} onChange={(v) => set('policy', v)} />
          </div>
        )}
        <label className="block text-sm"><span className="text-dim">Timeout (s)</span>
          <input type="number" className={field} value={form.timeout_seconds} onChange={(e) => set('timeout_seconds', e.target.value)} /></label>
        <label className="block text-sm"><span className="text-dim">Description</span>
          <input className={field} value={form.description} onChange={(e) => set('description', e.target.value)} /></label>
        <div className="flex justify-end gap-2 pt-2">
          <button className={btnGhost} onClick={onClose}>Cancel</button>
          <button className={btnPrimary} onClick={save} disabled={!form.id || !form.name || !form.entrypoint}>Create</button>
        </div>
      </div>
    </Modal>
  )
}

export default function Jobs({ onOpenJob, notify }) {
  const [jobs, setJobs] = useState(null)
  const [query, setQuery] = useState('')
  const [creating, setCreating] = useState(false)

  const load = () => api.jobs().then(setJobs).catch(() => setJobs([]))
  useEffect(() => { load(); const t = setInterval(load, 4000); return () => clearInterval(t) }, [])

  const act = (fn, msg) => fn.then(() => { notify(msg); load() }).catch((e) => notify(e.message, true))

  if (jobs === null) return <Spinner label="loading automations…" />
  const shown = jobs.filter((j) => !query || j.name.toLowerCase().includes(query.toLowerCase()) || (j.tags || []).some((t) => t.includes(query.toLowerCase())))

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="search automations…"
          className={`${field} !w-64`} aria-label="Search automations" />
        <button className={`${btnPrimary} ml-auto`} onClick={() => setCreating(true)}>+ New automation</button>
      </div>

      {shown.length === 0 ? (
        <Empty quip={query ? 'Nothing matches.' : 'No automations yet. Create your first one.'} />
      ) : (
        <div className="overflow-x-auto rounded-xl border border-edge">
          <table className="w-full bg-panel text-sm">
            <thead>
              <tr className="border-b border-edge text-left text-xs uppercase tracking-wider text-dim">
                {['status', 'name', 'schedule', 'last run', 'duration', 'next run', 'actions'].map((h) => (
                  <th key={h} className="px-4 py-3 font-normal">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {shown.map((j) => (
                <tr key={j.id} className="border-b border-edge/50 last:border-0 hover:bg-edge/20">
                  <td className="px-4 py-3"><Badge status={j.enabled === false ? 'paused' : j.status} /></td>
                  <td className="px-4 py-3">
                    <button onClick={() => onOpenJob(j.id)} className="font-medium underline-offset-2 hover:underline">{j.name}</button>
                    <div className="flex gap-1.5 mt-0.5">{(j.tags || []).map((t) => <Tag key={t} name={t} />)}</div>
                    {j.current_step && <div className="mt-1 text-xs text-dim mono truncate max-w-64">→ {j.current_step}</div>}
                    {['failed', 'timeout'].includes(j.status) && j.last_run?.error && (
                      <div className="mt-1 text-xs mono" style={{ color: 'var(--color-bad)' }}>{j.last_run.error}</div>
                    )}
                  </td>
                  <td className="px-4 py-3 mono text-dim">{humanCron(j.schedule)}</td>
                  <td className="px-4 py-3 mono text-dim text-xs">{fmtTime(j.last_run?.started_at)}</td>
                  <td className="px-4 py-3 mono text-dim">{fmtMs(j.last_run?.duration_ms)}</td>
                  <td className="px-4 py-3 mono text-dim text-xs">{fmtTime(j.next_run)}</td>
                  <td className="px-4 py-3">
                    <span className="flex flex-wrap gap-1.5 text-xs">
                      <button className={btnGhost} onClick={() => act(api.run(j.id), `${j.name}: run started`)}>Run</button>
                      <button className={btnGhost} onClick={() => act(api.run(j.id, true), `${j.name}: dry run started`)}>Dry</button>
                      {['failed', 'timeout'].includes(j.status) && j.last_run && (
                        <button className={btnGhost} onClick={() => act(api.retry(j.last_run.id), 'retry started')}>Retry</button>
                      )}
                      <button className={btnGhost} onClick={() => act(api.patch(j.id, { enabled: !(j.enabled !== false) }), j.enabled !== false ? 'paused' : 'resumed')}>
                        {j.enabled !== false ? 'Pause' : 'Resume'}
                      </button>
                      <button className={btnGhost} onClick={() => act(api.duplicateJob(j.id), 'duplicated (disabled by default)')}>Duplicate</button>
                      <button className={btnGhost} style={{ color: 'var(--color-bad)' }}
                        onClick={() => confirm(`Delete automation "${j.name}"? Its run history stays; the config is backed up.`) && act(api.deleteJob(j.id), 'deleted')}>
                        Delete
                      </button>
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {creating && <CreateJob notify={notify} onClose={() => setCreating(false)} onCreated={() => { setCreating(false); load() }} />}
    </div>
  )
}
