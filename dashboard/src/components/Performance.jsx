// Performance: real search + traffic data from GSC/GA4, and the rules that turn it into
// work: page-1 pushes, CTR rewrites, cannibalization, new queries, declines, refresh plan.
import { useEffect, useState } from 'react'
import { api } from '../api'
import { btnGhost, btnPrimary, Empty, fmtTime, Spinner } from './bits'

const short = (u) => (u || '').replace(/^https?:\/\/[^/]+/, '') || '/'
const delta = (now, before) => {
  if (!before) return null
  const d = Math.round(((now - before) / before) * 100)
  return <span className="ml-1 text-xs" style={{ color: d >= 0 ? 'var(--color-ok)' : 'var(--color-bad)' }}>{d >= 0 ? '+' : ''}{d}%</span>
}
const ACTION_TONE = { Redirect: 'var(--color-bad)', Merge: 'var(--color-accent)', Refresh: 'var(--color-accent)', Expand: 'var(--color-run)', 'Re-optimize': 'var(--color-run)' }

function Tile({ label, value, before }) {
  return (
    <div className="rounded-xl border border-edge bg-panel px-4 py-3">
      <div className="text-2xl font-bold mono">{value ?? '—'}{before != null && delta(value, before)}</div>
      <div className="mt-0.5 text-xs uppercase tracking-widest text-dim">{label}</div>
    </div>
  )
}

function Sparkline({ daily }) {
  if (!daily?.length) return null
  const max = Math.max(...daily.map((d) => d.clicks), 1)
  const pts = daily.map((d, i) => `${(i / Math.max(daily.length - 1, 1)) * 300},${40 - (d.clicks / max) * 38}`).join(' ')
  return <svg viewBox="0 0 300 42" className="h-10 w-full" aria-label="clicks per day"><polyline points={pts} fill="none" stroke="var(--color-run)" strokeWidth="1.5" /></svg>
}

const Section = ({ title, hint, rows, quip, cols, render, action }) => (
  <section>
    <div className="mb-2 flex items-center gap-3">
      <h3 className="text-xs uppercase tracking-widest text-dim">{title} ({rows.length})</h3>
      <span className="text-xs text-dim">{hint}</span>
      {action}
    </div>
    {rows.length === 0 ? <p className="text-xs text-dim">{quip}</p> : (
      <div className="overflow-hidden rounded-xl border border-edge">
        <table className="w-full text-xs">
          <thead className="bg-panel text-left uppercase tracking-widest text-dim"><tr>{cols.map((c) => <th key={c} className="px-3 py-1.5">{c}</th>)}</tr></thead>
          <tbody>{rows.slice(0, 25).map((r, i) => <tr key={i} className="border-t border-edge">{render(r).map((cell, j) => <td key={j} className="px-3 py-1.5 mono">{cell}</td>)}</tr>)}</tbody>
        </table>
      </div>
    )}
  </section>
)

export default function Performance({ notify, onNavigate }) {
  const [st, setSt] = useState(null)
  const [d, setD] = useState(null)
  const [busy, setBusy] = useState(false)
  const load = () => Promise.all([api.googleStatus(), api.insights()]).then(([s, i]) => { setSt(s); setD(i) }).catch((e) => notify(e.message, true))
  useEffect(() => { load() }, [])
  if (!st || !d) return <Spinner label="loading performance…" />
  const sync = () => { setBusy(true); api.googleSync().then((r) => notify(r.started ? 'sync started - see Logs' : r.detail)).catch((e) => notify(e.message, true)).finally(() => setBusy(false)) }
  const adopt = () => api.adoptKeywords().then((r) => { notify(`${r.added} queries added to Keywords`); load() }).catch((e) => notify(e.message, true))

  if (!st.connected || (!st.rows.gsc && !st.rows.ga4)) {
    return (
      <div className="max-w-xl rounded-xl border border-edge bg-panel p-8 text-center">
        <p className="text-sm text-dim">{!st.connected ? 'Connect Google on the Sites page, set the Search Console and GA4 properties, then sync.'
          : 'Google is connected. Run the first sync to pull 90 days of queries, clicks, positions and organic sessions.'}</p>
        <div className="mt-4 flex justify-center gap-2">
          {!st.connected ? <button className={btnPrimary} onClick={() => onNavigate('sites')}>Open Sites</button>
            : <button className={btnPrimary} disabled={busy} onClick={sync}>Sync now</button>}
        </div>
        {st.last_sync?.gsc?.error && <p className="mt-3 text-xs" style={{ color: 'var(--color-bad)' }}>last GSC sync: {st.last_sync.gsc.error}</p>}
        {st.last_sync?.ga4?.error && <p className="mt-1 text-xs" style={{ color: 'var(--color-bad)' }}>last GA4 sync: {st.last_sync.ga4.error}</p>}
      </div>
    )
  }
  const r = d.report
  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 md:flex-row md:items-center">
        <div className="grid flex-1 grid-cols-2 gap-3 md:grid-cols-5">
          <Tile label="clicks" value={r.search.now.clicks} before={r.search.before.clicks} />
          <Tile label="impressions" value={r.search.now.impressions} before={r.search.before.impressions} />
          <Tile label="queries" value={r.search.now.queries} />
          <Tile label="organic sessions" value={r.organic.now.sessions} before={r.organic.before.sessions} />
          <Tile label="organic conversions" value={Math.round(r.organic.now.conversions)} before={r.organic.before.conversions} />
        </div>
        <div className="text-right text-xs text-dim mono">
          <button className={btnGhost} disabled={busy} onClick={sync}>{busy ? 'Starting…' : 'Sync now'}</button>
          <p className="mt-1">{r.window.days} days to {r.window.to}</p>
          <p>GSC {st.last_sync.gsc ? fmtTime(st.last_sync.gsc.at) : 'never'} · GA4 {st.last_sync.ga4 ? fmtTime(st.last_sync.ga4.at) : 'never'}</p>
        </div>
      </div>
      <Sparkline daily={r.daily} />

      <Section title="Refresh plan" hint="one action per page, worst first" rows={d.refresh_plan} quip="Nothing needs a refresh." cols={['action', 'page', 'why']}
        render={(p) => [<span style={{ color: ACTION_TONE[p.action] }}>{p.action}</span>, short(p.page), <span className="text-dim">{p.reasons.join(' · ')}</span>]} />
      <Section title="Page-1 opportunities" hint="positions 8-20 with impressions - a content or link push away" rows={d.page1} quip="No striking-distance queries." cols={['query', 'page', 'position', 'impressions', 'clicks']}
        render={(x) => [x.query, short(x.page), x.position, x.impressions, x.clicks]} />
      <Section title="CTR opportunities" hint="page-1 rankings earning under half the expected clicks - rewrite title/meta" rows={d.ctr} quip="No weak-CTR pages." cols={['page', 'position', 'ctr', 'expected', 'impressions', 'missed clicks']}
        render={(x) => [short(x.page), x.position, `${(x.ctr * 100).toFixed(1)}%`, `${(x.expected_ctr * 100).toFixed(0)}%`, x.impressions, x.missed_clicks]} />
      <Section title="Cannibalization" hint="one query, several of your pages" rows={d.cannibalization} quip="No competing pages." cols={['query', 'impressions', 'pages']}
        render={(x) => [x.query, x.impressions, <span>{x.pages.map((p) => `${short(p.page)} (#${p.position})`).join('  ·  ')}</span>]} />
      <Section title="New keyword opportunities" hint="queries Google shows you for that Keywords does not track" rows={d.new_keywords} quip="Every query is already tracked." cols={['query', 'page', 'position', 'impressions']}
        render={(x) => [x.query, short(x.page), x.position, x.impressions]}
        action={d.new_keywords.length > 0 && <button className={`${btnGhost} ml-auto`} onClick={adopt}>Add top {Math.min(50, d.new_keywords.length)} to Keywords</button>} />
      <Section title="Ranking decline" hint="weighted position worse by 3+ vs the previous 28 days" rows={d.ranking_decline} quip="No page lost ground." cols={['page', 'before', 'now', 'clicks before', 'clicks now']}
        render={(x) => [short(x.page), x.position_before, x.position_now, x.clicks_before, x.clicks_now]} />
      <Section title="Traffic decline" hint="organic sessions down 30%+ vs the previous 28 days" rows={d.traffic_decline} quip="No page lost organic traffic." cols={['page', 'sessions before', 'now', 'drop']}
        render={(x) => [short(x.page), x.sessions_before, x.sessions_now, `${x.drop}%`]} />
      <Section title="Top landing pages" hint="organic sessions this window" rows={r.top_pages} quip="No organic sessions recorded." cols={['page', 'sessions', 'conversions']}
        render={(x) => [short(x.landing_page), x.sessions, Math.round(x.conversions)]} />
    </div>
  )
}
