import { useEffect, useRef, useState } from 'react'
import { api, liveLog } from '../api'
import { Dot, fmtMs, fmtTime, humanCron, PolicyField, ScheduleField, Sparkline, Tag } from './bits'

const TABS = ['overview', 'config', 'source', 'runs']

function LogView({ runId }) {
  const [lines, setLines] = useState([])
  const bottom = useRef(null)
  useEffect(() => {
    // WS replays history from cursor 0, so no separate fetch — avoids duplicate lines.
    setLines([])
    const close = liveLog(runId, (l) => setLines((p) => [...p, l]), () => {})
    return close
  }, [runId])
  useEffect(() => bottom.current?.scrollIntoView({ behavior: 'smooth' }), [lines])
  return (
    <pre className="mt-3 max-h-80 overflow-auto rounded-lg border border-edge bg-base p-3 text-xs mono">
      {lines.map((l) => (
        <div key={l.id ?? Math.random()} className={`log-line ${l.stream === 'stderr' ? 'text-bad' : l.stream === 'system' ? 'text-dim' : ''}`}>
          {l.line}
        </div>
      ))}
      <div ref={bottom} />
    </pre>
  )
}

function Config({ job, notify, reload }) {
  const [form, setForm] = useState({
    schedule: job.schedule,
    timeout_seconds: job.timeout_seconds || 300,
    alert_on_failure: job.alert_on_failure !== false,
    policy: (job.args || {}).policy || 'draft',
  })
  const isBlogJob = (job.entrypoint || '').includes('blog')
  const dirty =
    form.schedule !== job.schedule ||
    Number(form.timeout_seconds) !== (job.timeout_seconds || 300) ||
    form.alert_on_failure !== (job.alert_on_failure !== false) ||
    form.policy !== ((job.args || {}).policy || 'draft')

  const save = () => {
    const { policy, ...rest } = form
    const payload = { ...rest, timeout_seconds: Number(form.timeout_seconds) }
    if (isBlogJob) payload.args = { ...(job.args || {}), policy }
    return api
      .patch(job.id, payload)
      .then(() => { notify('config saved'); reload() })
      .catch((e) => notify(e.message, true))
  }

  const field = 'w-full rounded-lg border border-edge bg-base px-3 py-2 text-sm mono outline-none focus:border-accent'
  return (
    <div className="max-w-md space-y-4">
      <div className="block text-sm">
        <span className="text-dim">Schedule (UTC)</span>
        <ScheduleField value={form.schedule} onChange={(v) => setForm({ ...form, schedule: v })} />
      </div>
      {isBlogJob && (
        <div className="block text-sm">
          <span className="text-dim">Publish policy</span>
          <PolicyField value={form.policy} onChange={(v) => setForm({ ...form, policy: v })} />
        </div>
      )}
      <label className="block text-sm">
        <span className="text-dim">Timeout (seconds)</span>
        <input type="number" min="1" className={field} value={form.timeout_seconds} onChange={(e) => setForm({ ...form, timeout_seconds: e.target.value })} />
      </label>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={form.alert_on_failure} onChange={(e) => setForm({ ...form, alert_on_failure: e.target.checked })} />
        Alert on failure
      </label>
      <div className="text-sm text-dim">
        Env keys: <span className="mono">{(job.env || []).join(', ') || 'none'}</span>
      </div>
      <button onClick={save} disabled={!dirty} className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-black disabled:opacity-40">
        Save changes
      </button>
    </div>
  )
}

function Source({ job, notify }) {
  const [body, setBody] = useState(job.source)
  const [saved, setSaved] = useState(job.source)
  const save = () =>
    api.saveSource(job.id, body)
      .then(() => { setSaved(body); notify('source saved (backup created)') })
      .catch((e) => notify(e.message, true))
  return (
    <div className="space-y-3">
      <textarea
        value={body}
        onChange={(e) => setBody(e.target.value)}
        spellCheck={false}
        className="h-96 w-full rounded-lg border border-edge bg-base p-3 text-xs mono outline-none focus:border-accent"
        aria-label="Script source"
      />
      <button onClick={save} disabled={body === saved} className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-black disabled:opacity-40">
        Save (syntax-checked, backed up)
      </button>
    </div>
  )
}

export default function JobDetail({ jobId, onBack, notify }) {
  const [job, setJob] = useState(null)
  const [tab, setTab] = useState('overview')
  const [openRun, setOpenRun] = useState(null)

  const reload = () => api.job(jobId).then(setJob).catch((e) => notify(e.message, true))
  useEffect(() => {
    reload()
    const t = setInterval(reload, 5000)
    return () => clearInterval(t)
  }, [jobId])

  if (!job) return <p className="text-dim">loading…</p>

  const ok = job.runs.filter((r) => r.status === 'success').length
  const doneRuns = job.runs.filter((r) => r.status !== 'running').length
  const lastError = job.runs.find((r) => r.error)

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-4">
        <button onClick={onBack} className="text-sm text-dim hover:text-ink">← jobs</button>
        <h1 className="text-2xl font-bold">{job.name}</h1>
        <Dot status={job.enabled === false ? 'paused' : job.status} />
        <span className="flex gap-1.5">{(job.tags || []).map((t) => <Tag key={t} name={t} />)}</span>
        <span className="ml-auto flex gap-2">
          <button onClick={() => api.run(job.id).then(() => notify('run started')).catch((e) => notify(e.message, true))} className="rounded-lg bg-accent px-4 py-1.5 text-sm font-medium text-black">Run now</button>
          <button onClick={() => api.run(job.id, true).then(() => notify('dry run started')).catch((e) => notify(e.message, true))} className="rounded-lg border border-edge px-4 py-1.5 text-sm">Dry run</button>
        </span>
      </div>

      <nav className="flex gap-1 border-b border-edge" role="tablist">
        {TABS.map((t) => (
          <button
            key={t}
            role="tab"
            aria-selected={tab === t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm capitalize ${tab === t ? 'border-b-2 border-accent text-ink' : 'text-dim'}`}
          >
            {t}
          </button>
        ))}
      </nav>

      {tab === 'overview' && (
        <div className="grid gap-4 md:grid-cols-2">
          <div className="rounded-xl border border-edge bg-panel p-5">
            <h3 className="text-xs uppercase tracking-widest text-dim">last 30 durations</h3>
            <div className="mt-3"><Sparkline values={job.durations} /></div>
            <p className="mt-3 text-sm text-dim mono">
              success {doneRuns ? Math.round((ok / doneRuns) * 100) : '—'}% · next {fmtTime(job.next_run)}
            </p>
          </div>
          <div className="rounded-xl border border-edge bg-panel p-5">
            <h3 className="text-xs uppercase tracking-widest text-dim">last error</h3>
            <p className="mt-3 text-sm mono" style={{ color: lastError ? 'var(--color-bad)' : undefined }}>
              {lastError ? `#${lastError.id}: ${lastError.error}` : 'none so far'}
            </p>
          </div>
        </div>
      )}

      {tab === 'config' && <Config job={job} notify={notify} reload={reload} />}
      {tab === 'source' && <Source job={job} notify={notify} />}

      {tab === 'runs' && (
        <div className="space-y-2">
          {job.runs.map((r) => (
            <div key={r.id} className="rounded-lg border border-edge bg-panel">
              <button onClick={() => setOpenRun(openRun === r.id ? null : r.id)} className="flex w-full items-center gap-4 px-4 py-2.5 text-sm mono">
                <Dot status={r.status} />
                <span className="text-dim">#{r.id}</span>
                <span>{fmtTime(r.started_at)}</span>
                <span className="text-dim">{fmtMs(r.duration_ms)}</span>
                <span className="text-dim">exit {r.exit_code ?? '—'}</span>
                {r.dry_run === 1 && <span className="text-xs text-dim">(dry)</span>}
                {r.status === 'running' && (
                  <span
                    role="button"
                    onClick={(e) => { e.stopPropagation(); api.stop(r.id).then(reload) }}
                    className="ml-auto rounded border border-bad px-2 py-0.5 text-xs"
                    style={{ color: 'var(--color-bad)' }}
                  >
                    Stop
                  </span>
                )}
              </button>
              {openRun === r.id && <div className="px-4 pb-3"><LogView runId={r.id} /></div>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
