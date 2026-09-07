// Keywords: research -> clusters -> URL mapping -> cannibalization -> content gaps.
// Every model output is a suggestion; merge/split/move/approve are the human controls.
import { useEffect, useState } from 'react'
import { api } from '../api'
import { btnGhost, btnPrimary, Empty, field, Modal, Spinner } from './bits'

const INTENT_TONE = { informational: 'var(--color-run)', commercial: 'var(--color-accent)', transactional: 'var(--color-ok)', navigational: 'var(--color-dim)' }
const ACTION_TONE = { existing: 'var(--color-ok)', improve: 'var(--color-accent)', new: 'var(--color-run)', ignore: 'var(--color-dim)', '': 'var(--color-dim)' }
const short = (u) => (u || '').replace(/^https?:\/\/[^/]+/, '') || (u ? '/' : '')

const Tabs = ({ tab, setTab, items }) => (
  <nav className="mb-5 flex gap-1 overflow-x-auto whitespace-nowrap border-b border-edge" role="tablist">
    {items.map(([k, label]) => (
      <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
        className={`px-4 py-2 text-sm ${tab === k ? 'border-b-2 border-accent text-ink' : 'text-dim'}`}>{label}</button>
    ))}
  </nav>
)

export default function Keywords({ notify }) {
  const [tab, setTab] = useState('clusters')
  const [data, setData] = useState(null)
  const [busy, setBusy] = useState('')
  const load = () => api.keywords().then(setData).catch((e) => notify(e.message, true))
  useEffect(() => { load() }, [])
  const run = (step, label) => {
    setBusy(step)
    api.keywordRun(step).then((r) => { notify(`${label}: ${Object.entries(r).map(([k, v]) => `${k} ${v}`).join(', ')}`); load() })
      .catch((e) => notify(e.message, true)).finally(() => setBusy(''))
  }
  if (!data) return <Spinner />
  const c = data.counts
  return (
    <div>
      <div className="mb-5 flex flex-col gap-3 md:flex-row md:items-center">
        <div className="grid flex-1 grid-cols-2 gap-3 md:grid-cols-5">
          {[['keywords', c.keywords], ['clusters', c.clusters], ['unclustered', c.unclustered], ['unmapped', c.unmapped], ['approved maps', c.approved]].map(([l, v]) => (
            <div key={l} className="rounded-xl border border-edge bg-panel px-4 py-3"><div className="text-2xl font-bold mono">{v}</div><div className="mt-0.5 text-xs uppercase tracking-widest text-dim">{l}</div></div>
          ))}
        </div>
        <div className="flex flex-col gap-1 md:shrink-0">
          {[['research', 'Research from profile · ~1 min'], ['cluster', 'Cluster loose keywords · ~1 min'], ['map', 'Map clusters to URLs · ~1 min']].map(([step, label]) => (
            <button key={step} className={btnGhost} disabled={!!busy} onClick={() => run(step, label)}>{busy === step ? 'Working…' : label}</button>
          ))}
          <button className={btnGhost} disabled={!!busy} title="Web-search the top 10 clusters and validate intent against real results"
            onClick={() => { setBusy('serp'); api.serpTop().then((r) => { notify(`SERP analysed ${r.analysed} cluster(s)${r.errors.length ? `, ${r.errors.length} failed` : ''}`); load() }).catch((e) => notify(e.message, true)).finally(() => setBusy('')) }}>
            {busy === 'serp' ? 'Searching… (about 30s per cluster)' : 'Analyse SERPs (top 10) · ~5 min'}</button>
        </div>
      </div>
      <Tabs tab={tab} setTab={setTab} items={[['clusters', 'Clusters & mapping'], ['loose', `Unclustered (${c.unclustered})`], ['cannibal', 'Cannibalization'], ['gaps', 'Content gaps & pillars'], ['competitors', 'SEO competitors']]} />
      {tab === 'clusters' && <Clusters data={data} reload={load} notify={notify} />}
      {tab === 'loose' && <Loose data={data} reload={load} notify={notify} />}
      {tab === 'cannibal' && <Cannibal notify={notify} />}
      {tab === 'gaps' && <Gaps notify={notify} />}
      {tab === 'competitors' && <Competitors notify={notify} />}
    </div>
  )
}

function Clusters({ data, reload, notify }) {
  const [open, setOpen] = useState(null)
  if (data.clusters.length === 0) return <Empty quip="No clusters yet. Fill the business profile, then Research → Cluster → Map." />
  return (
    <div className="space-y-2">
      {data.clusters.map((cl) => (
        <button key={cl.id} onClick={() => setOpen(cl)} className="flex w-full flex-wrap items-center gap-3 rounded-lg border border-edge bg-panel px-4 py-2.5 text-left text-sm hover:border-accent">
          <span className="mono w-8 text-right font-bold">{cl.priority}</span>
          <span className="font-medium">{cl.name}</span>
          <span className="mono text-[10px] uppercase" style={{ color: INTENT_TONE[cl.intent] }}>{cl.intent}</span>
          <span className="mono text-[10px] uppercase text-dim">{cl.role}</span>
          <span className="text-xs text-dim">{cl.keywords.length} kw · {cl.keywords.find((k) => k.is_primary)?.text}</span>
          <span className="ml-auto mono text-xs" style={{ color: ACTION_TONE[cl.action] }}>{cl.action || 'unmapped'} {cl.target_url && short(cl.target_url)}</span>
          {cl.serp?.intent && <span className="mono text-[10px]" style={{ color: cl.serp.intent_matches ? 'var(--color-ok)' : 'var(--color-bad)' }}>SERP {cl.serp.intent}{cl.serp.mixed ? ' (mixed)' : ''}{cl.serp.own_rank ? ` · you #${cl.serp.own_rank}` : ''}</span>}
          {cl.approved && <span className="mono text-xs" style={{ color: 'var(--color-ok)' }}>✓ approved</span>}
        </button>
      ))}
      {open && <ClusterDrawer cluster={open} all={data.clusters} notify={notify} onClose={() => { setOpen(null); reload() }} />}
    </div>
  )
}

function ClusterDrawer({ cluster, all, notify, onClose }) {
  const [cl, setCl] = useState(cluster)
  const [sel, setSel] = useState([])
  const [splitName, setSplitName] = useState('')
  const [mergeFrom, setMergeFrom] = useState('')
  const patch = (body) => api.patchCluster(cl.id, body).then(setCl).catch((e) => notify(e.message, true))
  const refresh = () => api.keywords().then((d) => setCl(d.clusters.find((x) => x.id === cl.id) || cl))
  return (
    <Modal title={cl.name} onClose={onClose} wide>
      <div className="space-y-4 text-sm">
        <div className="grid gap-3 md:grid-cols-3">
          <label className="text-xs uppercase tracking-widest text-dim">Intent<select className={`${field} mt-1`} value={cl.intent} onChange={(e) => patch({ intent: e.target.value })}>{Object.keys(INTENT_TONE).map((i) => <option key={i}>{i}</option>)}</select></label>
          <label className="text-xs uppercase tracking-widest text-dim">Role<select className={`${field} mt-1`} value={cl.role} onChange={(e) => patch({ role: e.target.value })}>{['pillar', 'cluster', 'supporting'].map((i) => <option key={i}>{i}</option>)}</select></label>
          <label className="text-xs uppercase tracking-widest text-dim">Action<select className={`${field} mt-1`} value={cl.action} onChange={(e) => patch({ action: e.target.value })}><option value="">unmapped</option>{['existing', 'improve', 'new', 'ignore'].map((i) => <option key={i}>{i}</option>)}</select></label>
          <label className="text-xs uppercase tracking-widest text-dim md:col-span-2">Target URL<input className={`${field} mt-1 mono`} defaultValue={cl.target_url} onBlur={(e) => e.target.value !== cl.target_url && patch({ target_url: e.target.value })} /></label>
          <label className="text-xs uppercase tracking-widest text-dim">Parent topic<input className={`${field} mt-1`} defaultValue={cl.parent_topic} onBlur={(e) => e.target.value !== cl.parent_topic && patch({ parent_topic: e.target.value })} /></label>
        </div>
        {cl.reason && <p className="text-xs text-dim">{cl.reason}</p>}
        <SerpPanel cl={cl} setCl={setCl} notify={notify} />
        <div className="flex items-center gap-2">
          <button className={cl.approved ? btnGhost : btnPrimary} onClick={() => patch({ approved: !cl.approved })}>{cl.approved ? 'Un-approve mapping' : 'Approve mapping'}</button>
          <select className={`${field} ml-auto w-56`} value={mergeFrom} onChange={(e) => setMergeFrom(e.target.value)}><option value="">merge another cluster in…</option>{all.filter((x) => x.id !== cl.id).map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select>
          <button className={btnGhost} disabled={!mergeFrom} onClick={() => api.mergeCluster(cl.id, +mergeFrom).then((r) => { setCl(r); setMergeFrom(''); notify('merged') }).catch((e) => notify(e.message, true))}>Merge</button>
          <button className={btnGhost} onClick={() => api.deleteCluster(cl.id).then(onClose)}>Dissolve</button>
        </div>
        <div>
          <div className="mb-1 text-xs uppercase tracking-widest text-dim">Keywords</div>
          <ul className="divide-y divide-edge rounded-lg border border-edge">
            {cl.keywords.map((k) => (
              <li key={k.id} className="flex items-center gap-3 px-3 py-1.5 text-xs">
                <input type="checkbox" checked={sel.includes(k.id)} onChange={(e) => setSel(e.target.checked ? [...sel, k.id] : sel.filter((x) => x !== k.id))} />
                <span className={`mono ${k.is_primary ? 'font-bold' : ''}`}>{k.text}</span>
                {k.is_primary && <span className="mono text-[10px] uppercase" style={{ color: 'var(--color-ok)' }}>primary</span>}
                <span className="text-dim">rel {k.relevance} · com {k.commercial} · {k.intent}</span>
                {k.found_on?.length > 0 && <span className="mono text-dim" title={k.found_on.join('\n')}>on {k.found_on.length} page{k.found_on.length > 1 ? 's' : ''}</span>}
                <span className="ml-auto flex gap-2">
                  {!k.is_primary && <button className="text-dim hover:text-ink" onClick={() => api.keywordPrimary(k.id).then(refresh)}>make primary</button>}
                  <button className="text-dim hover:text-ink" onClick={() => api.keywordMove(k.id, null).then(refresh)}>unassign</button>
                </span>
              </li>
            ))}
          </ul>
          <div className="mt-2 flex gap-2">
            <input className={field} placeholder="new cluster name for selected keywords" value={splitName} onChange={(e) => setSplitName(e.target.value)} />
            <button className={btnGhost} disabled={!sel.length || !splitName.trim()} onClick={() => api.splitCluster(cl.id, sel, splitName).then(() => { notify('split'); onClose() }).catch((e) => notify(e.message, true))}>Split ({sel.length})</button>
          </div>
        </div>
      </div>
    </Modal>
  )
}

function Loose({ data, reload, notify }) {
  const [text, setText] = useState('')
  const add = () => api.addKeyword(text).then(() => { setText(''); reload() }).catch((e) => notify(e.message, true))
  return (
    <div className="space-y-3">
      <div className="flex gap-2">
        <input className={field} placeholder="add a keyword by hand" value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && add()} />
        <button className={btnGhost} disabled={!text.trim()} onClick={add}>Add</button>
      </div>
      {data.unclustered.length === 0 ? <Empty quip="Everything is clustered." /> : (
        <table className="w-full text-xs">
          <thead className="text-left uppercase tracking-widest text-dim"><tr><th className="py-1">keyword</th><th>source</th><th>intent</th><th>rel</th><th>com</th><th>move to</th><th /></tr></thead>
          <tbody>
            {data.unclustered.map((k) => (
              <tr key={k.id} className="border-t border-edge">
                <td className="py-1 mono">{k.text}</td><td className="text-dim">{k.source}</td><td style={{ color: INTENT_TONE[k.intent] }}>{k.intent || '—'}</td><td className="mono">{k.relevance}</td><td className="mono">{k.commercial}</td>
                <td><select className="rounded border border-edge bg-base px-1 py-0.5" defaultValue="" onChange={(e) => e.target.value && api.keywordMove(k.id, +e.target.value).then(reload)}><option value="">cluster…</option>{data.clusters.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></td>
                <td><button className="text-dim hover:text-ink" onClick={() => api.deleteKeyword(k.id).then(reload)}>✕</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

function Cannibal({ notify }) {
  const [rows, setRows] = useState(null)
  useEffect(() => { api.cannibalization().then(setRows).catch((e) => notify(e.message, true)) }, [])
  if (!rows) return <Spinner />
  if (rows.length === 0) return <Empty quip="No pages competing with each other." />
  return (
    <div className="space-y-2">
      {rows.map((i, n) => (
        <div key={n} className="rounded-lg border border-edge bg-panel p-3 text-xs">
          <div className="flex gap-2"><span className="mono uppercase" style={{ color: 'var(--color-accent)' }}>{i.type}</span><span className="mono">{i.keyword || short(i.url)}</span></div>
          <p className="mt-1 text-dim">{i.detail}</p>
          <p className="mt-1 mono">{(i.urls || i.found_on || i.clusters || []).map(short).join('  ·  ')}{i.mapped_to && <span> → mapped to {short(i.mapped_to)}</span>}</p>
        </div>
      ))}
    </div>
  )
}

function Gaps({ notify }) {
  const [g, setG] = useState(null)
  useEffect(() => { api.gaps().then(setG).catch((e) => notify(e.message, true)) }, [])
  if (!g) return <Spinner />
  const List = ({ title, rows, quip }) => (
    <section>
      <h3 className="mb-2 text-xs uppercase tracking-widest text-dim">{title} ({rows.length})</h3>
      {rows.length === 0 ? <p className="text-xs text-dim">{quip}</p> : rows.map((c) => (
        <div key={c.id} className="mb-1 flex flex-wrap items-center gap-3 rounded-lg border border-edge bg-panel px-3 py-2 text-xs">
          <span className="mono font-bold">{c.priority}</span><span className="font-medium">{c.name}</span>
          <span style={{ color: INTENT_TONE[c.intent] }}>{c.intent}</span><span className="mono text-dim">{c.primary}</span>
          {c.target_url && <span className="mono text-dim">{short(c.target_url)}</span>}
          <span className="ml-auto text-dim">{c.reason}</span>
        </div>
      ))}
    </section>
  )
  return (
    <div className="space-y-6">
      {g.unmapped > 0 && <p className="text-xs" style={{ color: 'var(--color-accent)' }}>{g.unmapped} cluster(s) not mapped yet - run “Map clusters to URLs”.</p>}
      <List title="Missing commercial pages" rows={g.missing_commercial_pages} quip="No commercial intent left unserved." />
      <List title="Existing pages to improve" rows={g.improve_existing} quip="Nothing flagged for improvement." />
      <List title="Supporting content to write" rows={g.supporting_content} quip="No supporting-content gaps." />
      <section>
        <h3 className="mb-2 text-xs uppercase tracking-widest text-dim">Pillar map</h3>
        {g.pillars.map((p) => (
          <div key={p.topic} className="mb-2 rounded-lg border border-edge bg-panel p-3 text-xs">
            <div className="font-medium">{p.topic}</div>
            <ul className="mt-1 flex flex-wrap gap-2">{p.clusters.map((c) => <li key={c.id} className="rounded border border-edge px-2 py-0.5"><span className="mono text-dim">{c.role}</span> {c.name} <span style={{ color: ACTION_TONE[c.action] }}>{c.action || 'unmapped'}</span></li>)}</ul>
          </div>
        ))}
      </section>
    </div>
  )
}


function SerpPanel({ cl, setCl, notify }) {
  const [busy, setBusy] = useState(false)
  const run = () => { setBusy(true); api.clusterSerp(cl.id).then((serp) => { setCl({ ...cl, serp }); notify('SERP analysed') }).catch((e) => notify(e.message, true)).finally(() => setBusy(false)) }
  const s = cl.serp || {}
  return (
    <div className="rounded-lg border border-edge bg-base p-3 text-xs">
      <div className="flex items-center gap-3">
        <span className="uppercase tracking-widest text-dim">SERP check</span>
        {s.fetched_at && <span className="text-dim mono">{s.keyword} · {new Date(s.fetched_at).toLocaleDateString()}</span>}
        <button className={`${btnGhost} ml-auto`} disabled={busy} onClick={run}>{busy ? 'Searching…' : s.fetched_at ? 'Re-check' : 'Analyse SERP'}</button>
      </div>
      {s.fetched_at && (
        <div className="mt-2 space-y-2">
          <p>Real intent: <b style={{ color: s.intent_matches ? 'var(--color-ok)' : 'var(--color-bad)' }}>{s.intent}</b>{s.mixed && <span style={{ color: 'var(--color-accent)' }}> · mixed intent</span>} · ranking format: <b>{s.content_type}</b>{s.own_rank ? <span> · you rank <b>#{s.own_rank}</b></span> : <span className="text-dim"> · you are not in the top {s.results?.length}</span>}</p>
          {s.serp_patterns?.length > 0 && <p className="text-dim">Titles have in common: {s.serp_patterns.join(' · ')}</p>}
          {s.gaps?.length > 0 && <p><span style={{ color: 'var(--color-accent)' }}>Gaps vs top results:</span> {s.gaps.join(' · ')}</p>}
          <p className="text-dim">{s.recommendation}</p>
          <ol className="list-decimal pl-5 mono">
            {(s.results || []).map((r) => <li key={r.url} style={r.own ? { color: 'var(--color-ok)' } : undefined}><a href={r.url} target="_blank" rel="noreferrer" className="hover:underline">{r.domain}</a> <span className="text-dim">{(r.title || '').slice(0, 70)}{r.words ? ` · ${r.words}w` : ''}</span></li>)}
          </ol>
        </div>
      )}
    </div>
  )
}

function Competitors({ notify }) {
  const [rows, setRows] = useState(null)
  useEffect(() => { api.competitors().then(setRows).catch((e) => notify(e.message, true)) }, [])
  if (!rows) return <Spinner />
  if (rows.length === 0) return <Empty quip="Run “Analyse SERPs” first - competitors are whoever keeps outranking you." />
  return (
    <div className="overflow-hidden rounded-xl border border-edge">
      <table className="w-full text-xs">
        <thead className="bg-panel text-left uppercase tracking-widest text-dim"><tr><th className="px-3 py-2">domain</th><th className="px-3 py-2">clusters</th><th className="px-3 py-2">best rank</th><th className="px-3 py-2">keywords they rank for</th></tr></thead>
        <tbody>{rows.map((c) => (
          <tr key={c.domain} className="border-t border-edge"><td className="px-3 py-1.5 mono">{c.domain}</td><td className="px-3 py-1.5 mono">{c.clusters}</td><td className="px-3 py-1.5 mono">#{c.best_rank}</td><td className="px-3 py-1.5 text-dim">{c.keywords.join(', ')}</td></tr>
        ))}</tbody>
      </table>
    </div>
  )
}
