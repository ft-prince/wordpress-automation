// Global run history: filters, expandable timestamped logs, retry.
import { useEffect, useState } from 'react'
import { api, liveLog } from '../api'
import { Badge, btnGhost, Empty, field, fmtMs, fmtTime, Spinner } from './bits'

function LogLines({ runId }) {
  const [lines, setLines] = useState([])
  useEffect(() => {
    setLines([])
    const close = liveLog(runId, (l) => setLines((p) => [...p, l]), () => {})
    return close
  }, [runId])
  return (
    <pre className="max-h-72 overflow-auto rounded-lg border border-edge bg-base p-3 text-xs mono">
      {lines.length === 0 && <span className="text-dim">no output</span>}
      {lines.map((l) => (
        <div key={l.id} className={`log-line ${l.stream === 'stderr' ? '' : l.stream === 'system' ? 'text-dim' : ''}`}
          style={l.stream === 'stderr' ? { color: 'var(--color-bad)' } : undefined}>
          <span className="text-dim">{(l.ts || '').slice(11, 19)}</span>  {l.line}
        </div>
      ))}
    </pre>
  )
}

export default function Logs({ notify }) {
  const [runs, setRuns] = useState(null)
  const [jobs, setJobs] = useState([])
  const [filterJob, setFilterJob] = useState('')
  const [filterStatus, setFilterStatus] = useState('')
  const [open, setOpen] = useState(null)

  const load = () => {
    const params = { limit: 100 }
    if (filterJob) params.job = filterJob
    if (filterStatus) params.status = filterStatus
    api.runs(params).then(setRuns).catch(() => setRuns([]))
  }
  useEffect(() => { api.jobs().then(setJobs).catch(() => {}) }, [])
  useEffect(() => { setRuns(null); load(); const t = setInterval(load, 6000); return () => clearInterval(t) }, [filterJob, filterStatus])

  const retry = (id) => api.retry(id).then(() => { notify(`retry of #${id} started`); load() }).catch((e) => notify(e.message, true))

  return (
    <div className="space-y-4">
      <div className="flex gap-3">
        <select className={`${field} !w-52`} value={filterJob} onChange={(e) => setFilterJob(e.target.value)} aria-label="Filter by automation">
          <option value="">All automations</option>
          {jobs.map((j) => <option key={j.id} value={j.id}>{j.name}</option>)}
        </select>
        <select className={`${field} !w-40`} value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)} aria-label="Filter by status">
          <option value="">All statuses</option>
          {['success', 'failed', 'timeout', 'running', 'killed'].map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </div>

      {runs === null ? <Spinner label="loading history…" /> : runs.length === 0 ? (
        <Empty quip="No runs match these filters." />
      ) : (
        <div className="space-y-1.5">
          {runs.map((r) => (
            <div key={r.id} className="rounded-lg border border-edge bg-panel">
              <button onClick={() => setOpen(open === r.id ? null : r.id)} className="flex w-full items-center gap-4 px-4 py-2.5 text-sm mono">
                <span className="text-dim w-10 text-left">#{r.id}</span>
                <Badge status={r.status} />
                <span>{r.job_id}</span>
                <span className="text-dim">{fmtTime(r.started_at)}</span>
                <span className="text-dim">{fmtMs(r.duration_ms)}</span>
                <span className="text-dim text-xs">{r.trigger}</span>
                {r.dry_run === 1 && <span className="text-xs text-dim">(dry)</span>}
                {r.error && <span className="truncate max-w-56 text-xs" style={{ color: 'var(--color-bad)' }} title={r.error}>{r.error}</span>}
                <span className="ml-auto flex gap-2">
                  {['failed', 'timeout', 'killed'].includes(r.status) && (
                    <span role="button" className={btnGhost} onClick={(e) => { e.stopPropagation(); retry(r.id) }}>Retry</span>
                  )}
                  {r.status === 'running' && (
                    <span role="button" className={btnGhost} style={{ color: 'var(--color-bad)' }}
                      onClick={(e) => { e.stopPropagation(); api.stop(r.id).then(load) }}>Stop</span>
                  )}
                </span>
              </button>
              {open === r.id && <div className="px-4 pb-3"><LogLines runId={r.id} /></div>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
