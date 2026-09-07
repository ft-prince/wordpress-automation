// Dedicated system health page: every subsystem with its state and last failure.
import { useEffect, useState } from 'react'
import { api } from '../api'
import { fmtTime, Spinner } from './bits'

function HealthCard({ title, ok, detail, sub }) {
  const color = ok === null ? 'var(--color-dim)' : ok ? 'var(--color-ok)' : 'var(--color-bad)'
  return (
    <div className="rounded-xl border bg-panel p-5" style={{ borderColor: ok === false ? color : 'var(--color-edge)' }}>
      <div className="flex items-center gap-2">
        <span className="h-2.5 w-2.5 rounded-full" style={{ background: color }} />
        <h3 className="text-sm font-medium">{title}</h3>
        <span className="ml-auto text-xs mono" style={{ color }}>{ok === null ? 'unknown' : ok ? 'operational' : 'down'}</span>
      </div>
      <p className="mt-2 text-sm text-dim mono">{detail}</p>
      {sub && <p className="mt-1 text-xs text-dim">{sub}</p>}
    </div>
  )
}

export default function Health() {
  const [h, setH] = useState(null)
  const [alerts, setAlerts] = useState([])
  useEffect(() => {
    const load = () => {
      api.health().then(setH).catch(() => setH(false))
      api.alerts().then(setAlerts).catch(() => {})
    }
    load()
    const t = setInterval(load, 8000)
    return () => clearInterval(t)
  }, [])

  if (h === null) return <Spinner label="checking systems…" />
  if (h === false) return <HealthCard title="Control plane" ok={false} detail="Can't reach the server. Is it running?" />

  const wp = h.wp || {}
  return (
    <div className="max-w-4xl space-y-6">
      <div className="grid gap-4 md:grid-cols-2">
        <HealthCard title="WordPress API" ok={wp.connected}
          detail={wp.connected ? `${wp.site} · ${wp.latency_ms}ms` : wp.error || 'unreachable'}
          sub={`last successful sync: ${wp.last_ok ? fmtTime(wp.last_ok) : 'never'}`} />
        <HealthCard title="Authentication" ok={wp.connected}
          detail={wp.connected ? `${wp.user} (${(wp.roles || []).join(', ')}) · ${wp.auth}` : 'auth cannot be verified while disconnected'} />
        <HealthCard title="Scheduler" ok={h.scheduler_running}
          detail={h.scheduler_running ? 'APScheduler running, jobs loaded from registry' : "The scheduler is stopped, so scheduled runs won't happen"} />
        <HealthCard title="Workers" ok={true}
          detail={`${h.workers_active ?? 0} run(s) executing now`}
          sub={`last successful run: ${h.last_successful_run ? fmtTime(h.last_successful_run) : 'never'}`} />
        <HealthCard title="Database" ok={h.db_ok} detail={h.db_ok ? 'SQLite · WAL mode' : 'database query failed'} />
        <HealthCard title="Data freshness" ok={(h.freshness?.crawl_days ?? 99) <= 14 && (h.freshness?.gsc_days ?? 0) <= 4}
          detail={`crawl ${h.freshness?.crawl_days ?? '—'}d · Search Console ${h.freshness?.gsc_days ?? '—'}d · GA4 ${h.freshness?.ga4_days ?? '—'}d old`} />
        <HealthCard title="AI spend" ok={true}
          detail={`today $${h.llm?.today?.usd ?? 0} (${h.llm?.today?.calls ?? 0} calls) · 7d $${h.llm?.week?.usd ?? 0} · 30d $${h.llm?.month?.usd ?? 0} / ${((h.llm?.month?.tokens ?? 0) / 1000).toFixed(0)}k tokens`} />
        <HealthCard title="Last failed request" ok={wp.last_fail?.at ? false : true}
          detail={wp.last_fail?.at ? `${fmtTime(wp.last_fail.at)} — ${wp.last_fail.error}` : 'no failures recorded this session'} />
      </div>

      <section className="rounded-xl border border-edge bg-panel p-5">
        <h2 className="mb-3 text-sm uppercase tracking-widest text-dim">Active warnings</h2>
        {alerts.length === 0 ? (
          <p className="text-sm" style={{ color: 'var(--color-ok)' }}>All clear. Nothing needs your attention.</p>
        ) : (
          <ul className="space-y-1.5 text-sm">
            {alerts.map((a, i) => (
              <li key={i} className="mono">
                <span className="uppercase text-xs mr-2" style={{ color: a.level === 'warn' ? 'var(--color-accent)' : 'var(--color-bad)' }}>{a.level}</span>
                {a.text}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
