// Content page: business profile (what every prompt reads), the brief -> draft -> QA
// -> approve pipeline, and the change queue with one-click rollback.
import { useEffect, useState } from 'react'
import { api } from '../api'
import { btnGhost, btnPrimary, Empty, field, fmtTime, Modal, Spinner } from './bits'

const Tabs = ({ tab, setTab, items }) => (
  <nav className="mb-5 flex gap-1 overflow-x-auto whitespace-nowrap border-b border-edge" role="tablist">
    {items.map(([k, label]) => (
      <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
        className={`px-4 py-2 text-sm ${tab === k ? 'border-b-2 border-accent text-ink' : 'text-dim'}`}>{label}</button>
    ))}
  </nav>
)

export default function Content({ notify }) {
  const [tab, setTab] = useState('briefs')
  return (
    <div>
      <Tabs tab={tab} setTab={setTab} items={[['briefs', 'Briefs & drafts'], ['profile', 'Business profile'], ['changes', 'Change queue']]} />
      {tab === 'profile' && <Profile notify={notify} />}
      {tab === 'briefs' && <Briefs notify={notify} />}
      {tab === 'changes' && <Changes notify={notify} />}
    </div>
  )
}

// -- profile ------------------------------------------------------------------

const LIST = ['products', 'services', 'industries', 'locations', 'markets', 'facts', 'competitors']
const TEXT = [['name', 'Business name'], ['description', 'What the business does'], ['audience', 'Audience / ICP'], ['brand_voice', 'Brand voice']]
const toLines = (arr) => (arr || []).join('\n')
const fromLines = (s) => s.split('\n').map((x) => x.trim()).filter(Boolean)

function Profile({ notify }) {
  const [p, setP] = useState(null)
  const [busy, setBusy] = useState('')
  useEffect(() => { api.profile().then(setP).catch((e) => notify(e.message, true)) }, [])
  if (!p) return <Spinner />
  const set = (k, v) => setP({ ...p, [k]: v })
  const save = () => {
    setBusy('save')
    const body = Object.fromEntries([...TEXT.map(([k]) => [k, p[k] || '']), ...LIST.map((k) => [k, p[k] || []]), ['priorities', p.priorities || []]])
    api.saveProfile(body).then((r) => { setP(r); notify('profile saved') }).catch((e) => notify(e.message, true)).finally(() => setBusy(''))
  }
  const draft = () => {
    setBusy('draft')
    api.draftProfile().then((d) => { setP({ ...p, ...d }); notify('drafted from the crawl - review, then save') })
      .catch((e) => notify(e.message, true)).finally(() => setBusy(''))
  }
  const prios = p.priorities || []
  return (
    <div className="max-w-4xl space-y-4">
      <div className="flex items-center gap-3">
        <p className="text-sm text-dim">Every brief, draft, keyword score and QA check reads this. Facts listed here are the only claims the writer may state as fact.</p>
        <button className={`${btnGhost} ml-auto shrink-0`} disabled={!!busy} onClick={draft}>{busy === 'draft' ? 'Reading crawl…' : 'Draft from crawl'}</button>
        <button className={btnPrimary} disabled={!!busy} onClick={save}>{busy === 'save' ? 'Saving…' : 'Save'}</button>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        {TEXT.map(([k, label]) => (
          <label key={k} className={`block text-xs uppercase tracking-widest text-dim ${k === 'description' || k === 'audience' ? 'md:col-span-2' : ''}`}>{label}
            {k === 'name' ? <input className={`${field} mt-1`} value={p[k] || ''} onChange={(e) => set(k, e.target.value)} />
              : <textarea className={`${field} mt-1 min-h-16`} value={p[k] || ''} onChange={(e) => set(k, e.target.value)} />}
          </label>
        ))}
        {LIST.map((k) => (
          <label key={k} className={`block text-xs uppercase tracking-widest text-dim ${k === 'facts' ? 'md:col-span-2' : ''}`}>{k} <span className="normal-case tracking-normal">(one per line)</span>
            <textarea className={`${field} mt-1 min-h-20 mono`} value={toLines(p[k])} onChange={(e) => set(k, fromLines(e.target.value))} />
          </label>
        ))}
        <div className="md:col-span-2">
          <div className="text-xs uppercase tracking-widest text-dim">Business priorities <span className="normal-case tracking-normal">(topic + weight 1-5; weights steer keyword and content priority)</span></div>
          {prios.map((pr, i) => (
            <div key={i} className="mt-1 flex gap-2">
              <input className={field} placeholder="topic / product line" value={pr.topic || ''} onChange={(e) => set('priorities', prios.map((x, j) => (j === i ? { ...x, topic: e.target.value } : x)))} />
              <input type="number" min="1" max="5" className={`${field} w-20`} value={pr.weight || 3} onChange={(e) => set('priorities', prios.map((x, j) => (j === i ? { ...x, weight: +e.target.value } : x)))} />
              <button className={btnGhost} onClick={() => set('priorities', prios.filter((_, j) => j !== i))}>✕</button>
            </div>
          ))}
          <button className={`${btnGhost} mt-2`} onClick={() => set('priorities', [...prios, { topic: '', weight: 3 }])}>+ priority</button>
        </div>
      </div>
    </div>
  )
}

// -- briefs -------------------------------------------------------------------

const STATUS_TONE = { brief: 'var(--color-dim)', drafted: 'var(--color-run)', qa: 'var(--color-accent)', approved: 'var(--color-ok)', published: 'var(--color-ok)', rejected: 'var(--color-bad)' }
const NEXT = { brief: ['draft', 'Write draft'], drafted: ['qa', 'Run QA'], qa: ['approve', 'Approve → WP draft'] }

function Briefs({ notify }) {
  const [rows, setRows] = useState(null)
  const [open, setOpen] = useState(null)
  const [title, setTitle] = useState('')
  const [busy, setBusy] = useState('')
  const load = () => api.briefs().then(setRows).catch((e) => notify(e.message, true))
  useEffect(() => { load() }, [])
  const create = () => {
    if (!title.trim()) return
    setBusy('create')
    api.createBrief({ title }).then((b) => { setTitle(''); notify('brief ready'); load(); setOpen(b.id) })
      .catch((e) => notify(e.message, true)).finally(() => setBusy(''))
  }
  if (!rows) return <Spinner />
  return (
    <div className="space-y-4">
      <div className="flex gap-2">
        <input className={field} placeholder="Article topic, e.g. 'How edge AI cuts false alarms in perimeter security'" value={title}
          onChange={(e) => setTitle(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && create()} />
        <button className={`${btnPrimary} shrink-0`} disabled={busy === 'create' || !title.trim()} onClick={create}>{busy === 'create' ? 'Briefing…' : 'New brief'}</button>
      </div>
      <p className="text-xs text-dim">Brief → draft → QA → approve. Approval creates a WordPress <b>draft</b>; publishing stays on the Posts page. The scheduled “Publish blog post” automation runs this same chain on the topic queue.</p>
      {rows.length === 0 ? <Empty quip="No briefs yet. Type a topic above, or approve topics and let the automation brief them." /> : (
        <div className="overflow-hidden rounded-xl border border-edge">
          <table className="w-full text-xs">
            <thead className="bg-panel text-left uppercase tracking-widest text-dim">
              <tr><th className="px-3 py-2">status</th><th className="px-3 py-2">title</th><th className="px-3 py-2">keyword</th><th className="px-3 py-2">intent</th><th className="px-3 py-2">QA</th><th className="px-3 py-2">updated</th></tr>
            </thead>
            <tbody>
              {rows.map((b) => (
                <tr key={b.id} className="cursor-pointer border-t border-edge hover:bg-edge/30" onClick={() => setOpen(b.id)}>
                  <td className="px-3 py-1.5 mono" style={{ color: STATUS_TONE[b.status] }}>{b.status}</td>
                  <td className="max-w-md truncate px-3 py-1.5">{b.draft_title || b.title}</td>
                  <td className="px-3 py-1.5 mono">{b.primary_keyword}</td>
                  <td className="px-3 py-1.5 mono text-dim">{b.intent}</td>
                  <td className="px-3 py-1.5 mono">{b.qa?.score != null ? `${b.qa.score} ${b.qa.verdict}` : '—'}</td>
                  <td className="px-3 py-1.5 mono text-dim">{fmtTime(b.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {open && <BriefDrawer id={open} notify={notify} onClose={() => { setOpen(null); load() }} />}
    </div>
  )
}

function BriefDrawer({ id, notify, onClose }) {
  const [b, setB] = useState(null)
  const [busy, setBusy] = useState('')
  const [edit, setEdit] = useState(false)
  const [form, setForm] = useState({})
  const load = () => api.brief(id).then((x) => { setB(x); setForm({ primary_keyword: x.primary_keyword, intent: x.intent, audience: x.audience, cta: x.cta, word_target: x.word_target, custom_instructions: x.custom_instructions, outline: x.outline.map((o) => o.h2).join('\n'), faqs: x.faqs.join('\n') }) }).catch((e) => { notify(e.message, true); onClose() })
  useEffect(() => { load() }, [id])
  if (!b) return <Modal title="Brief" onClose={onClose} wide><Spinner /></Modal>
  const act = (action) => {
    setBusy(action)
    api.briefAction(id, action).then((r) => { setB(r); notify(action === 'approve' ? `WordPress draft #${r.post?.id} created` : `${action} done`) })
      .catch((e) => notify(e.message, true)).finally(() => setBusy(''))
  }
  const saveEdit = () => {
    setBusy('save')
    api.patchBrief(id, { primary_keyword: form.primary_keyword, intent: form.intent, audience: form.audience, cta: form.cta, word_target: +form.word_target,
      custom_instructions: form.custom_instructions, outline: form.outline.split('\n').filter(Boolean).map((h2) => ({ h2, h3: [], notes: '' })), faqs: form.faqs.split('\n').filter(Boolean) })
      .then(() => { setEdit(false); load(); notify('brief updated') }).catch((e) => notify(e.message, true)).finally(() => setBusy(''))
  }
  const run = (name, fn) => { setBusy(name); fn().then(() => { notify(`${name} done`); load() }).catch((e) => notify(e.message, true)).finally(() => setBusy('')) }
  const next = NEXT[b.status]
  const qa = b.qa || {}
  const plan = b.link_plan || {}
  const inboundToPage = (url) => null
  return (
    <Modal title={b.draft_title || b.title} onClose={onClose} wide>
      <div className="space-y-4 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <span className="mono text-xs" style={{ color: STATUS_TONE[b.status] }}>{b.status}</span>
          <span className="mono text-xs text-dim">{b.intent} · {b.content_type} · target {b.word_target} words · {b.prompt_version}</span>
          {b.post_id && <span className="mono text-xs" style={{ color: 'var(--color-ok)' }}>WP #{b.post_id}</span>}
          <span className="ml-auto flex gap-2">
            {b.status !== 'approved' && b.status !== 'rejected' && <button className={btnGhost} onClick={() => setEdit(!edit)}>{edit ? 'Cancel edit' : 'Edit brief'}</button>}
            {b.status === 'qa' && <button className={btnGhost} disabled={!!busy} onClick={() => act('draft')}>Re-draft</button>}
            {b.draft_html && b.status !== 'approved' && <button className={btnGhost} disabled={!!busy} onClick={() => run('links', () => api.briefLinks(id))}>{busy === 'links' ? 'Linking…' : 'Suggest links'}</button>}
            {b.draft_html && b.status !== 'approved' && <button className={btnGhost} disabled={!!busy} onClick={() => run('schema', () => api.briefSchema(id))}>{busy === 'schema' ? 'Building…' : b.schema_jsonld?.['@graph'] ? 'Rebuild schema' : 'Generate schema'}</button>}
            {next && <button className={btnPrimary} disabled={!!busy} onClick={() => act(next[0])}>{busy === next[0] ? 'Working…' : next[1]}</button>}
            {b.status !== 'rejected' && b.status !== 'approved' && <button className={btnGhost} disabled={!!busy} onClick={() => act('reject')}>Reject</button>}
          </span>
        </div>

        {edit ? (
          <div className="grid gap-3 md:grid-cols-2">
            {[['primary_keyword', 'Primary keyword'], ['intent', 'Intent'], ['audience', 'Audience'], ['cta', 'CTA'], ['word_target', 'Word target']].map(([k, l]) => (
              <label key={k} className="block text-xs uppercase tracking-widest text-dim">{l}<input className={`${field} mt-1`} value={form[k] ?? ''} onChange={(e) => setForm({ ...form, [k]: e.target.value })} /></label>
            ))}
            <label className="block text-xs uppercase tracking-widest text-dim md:col-span-2">Outline (one H2 per line)<textarea className={`${field} mt-1 min-h-24 mono`} value={form.outline} onChange={(e) => setForm({ ...form, outline: e.target.value })} /></label>
            <label className="block text-xs uppercase tracking-widest text-dim">FAQs (one per line)<textarea className={`${field} mt-1 min-h-20`} value={form.faqs} onChange={(e) => setForm({ ...form, faqs: e.target.value })} /></label>
            <label className="block text-xs uppercase tracking-widest text-dim">Custom instructions for the writer<textarea className={`${field} mt-1 min-h-20`} value={form.custom_instructions} onChange={(e) => setForm({ ...form, custom_instructions: e.target.value })} /></label>
            <div className="md:col-span-2"><button className={btnPrimary} disabled={busy === 'save'} onClick={saveEdit}>Save brief</button></div>
          </div>
        ) : (
          <div className="grid gap-3 md:grid-cols-2">
            <Box label="Primary keyword"><span className="mono">{b.primary_keyword}</span> <span className="text-dim">+ {b.secondary_keywords.join(', ')}</span></Box>
            <Box label="Audience">{b.audience}</Box>
            <Box label="Outline"><ol className="list-decimal pl-4">{b.outline.map((o, i) => <li key={i}>{o.h2}{o.h3?.length ? <span className="text-dim"> → {o.h3.join(' · ')}</span> : null}</li>)}</ol></Box>
            <Box label="Must cover / FAQs / links">
              <p className="text-dim">{b.entities.join(', ')}</p>
              <ul className="mt-1 list-disc pl-4">{b.faqs.map((f, i) => <li key={i}>{f}</li>)}</ul>
              <p className="mt-1 mono text-xs">{b.internal_links.map((l) => l.url.replace(/^https?:\/\/[^/]+/, '')).join('  ')}</p>
              <p className="mt-1 text-dim">CTA: {b.cta}</p>
            </Box>
          </div>
        )}

        {b.draft_html && (
          <Box label={`Draft · ${b.draft_title}`}>
            <p className="mb-2 mono text-xs text-dim">meta: {b.draft_meta} ({b.draft_meta.length})</p>
            <div className="prose-sm max-h-80 overflow-y-auto rounded border border-edge bg-base p-3 text-xs leading-relaxed [&_h2]:mt-3 [&_h2]:font-bold [&_h3]:mt-2 [&_h3]:font-semibold [&_a]:underline [&_ul]:list-disc [&_ul]:pl-4" dangerouslySetInnerHTML={{ __html: b.draft_html }} />
          </Box>
        )}

        {(plan.outbound?.length > 0 || plan.inbound?.length > 0) && (
          <Box label="Internal links">
            {plan.outbound?.length > 0 && (
              <div className="text-xs">
                <div className="mb-1 flex items-center gap-2 text-dim">This article should link to
                  {b.status !== 'approved' && <button className={btnGhost} onClick={() => run('apply links', () => api.briefLinksApply(id))}>Insert into draft</button>}</div>
                <ul className="list-disc pl-4">{plan.outbound.map((l, i) => <li key={i}><span className="mono">{l.anchor}</span> → {l.url.replace(/^https?:\/\/[^/]+/, '')} <span className="text-dim">({l.section}) {l.reason}</span></li>)}</ul>
              </div>
            )}
            {plan.inbound?.length > 0 && (
              <div className="mt-2 text-xs">
                <div className="mb-1 text-dim">Existing pages that should link here (after publishing, replace the anchor with the live URL)</div>
                <ul className="list-disc pl-4">{plan.inbound.map((l, i) => <li key={i}>{l.url.replace(/^https?:\/\/[^/]+/, '')}: “{l.sentence}” <span className="text-dim">{l.reason}</span></li>)}</ul>
              </div>
            )}
          </Box>
        )}
        {b.schema_jsonld?.['@graph'] && (
          <Box label={`Structured data · ${b.schema_jsonld['@graph'].map((g) => g['@type']).join(' + ')} (injected on approve)`}>
            <pre className="max-h-40 overflow-auto text-[10px] text-dim">{JSON.stringify(b.schema_jsonld, null, 1)}</pre>
          </Box>
        )}
        {qa.score != null && (
          <Box label={`QA · ${qa.score}/100 · ${qa.verdict}`}>
            <ul className="grid gap-x-4 md:grid-cols-2">
              {qa.checks.map((c) => <li key={c.code} className="text-xs" style={{ color: c.ok ? 'var(--color-ok)' : 'var(--color-bad)' }}>{c.ok ? '✓' : '✗'} {c.detail}</li>)}
              <li className="text-xs" style={{ color: qa.duplicate?.ok ? 'var(--color-ok)' : 'var(--color-bad)' }}>{qa.duplicate?.ok ? '✓' : '✗'} {qa.duplicate?.detail}</li>
            </ul>
            {qa.model && !qa.model.error && (
              <div className="mt-2 space-y-1 text-xs">
                <p>Intent {qa.model.intent_score}/100 — {qa.model.intent_note}</p>
                {qa.model.missing_topics?.length > 0 && <p style={{ color: 'var(--color-accent)' }}>Missing: {qa.model.missing_topics.join(', ')}</p>}
                {qa.model.unsupported_claims?.length > 0 && <div style={{ color: 'var(--color-bad)' }}>Unsupported claims:<ul className="list-disc pl-4">{qa.model.unsupported_claims.map((c, i) => <li key={i}>{c}</li>)}</ul></div>}
                {qa.model.stuffing && <p style={{ color: 'var(--color-accent)' }}>Keyword stuffing: {qa.model.stuffing_example}</p>}
                <p className="text-dim">Readability grade {qa.model.readability_grade} — {qa.model.readability_fix}. {qa.model.audience_note}</p>
              </div>
            )}
          </Box>
        )}
      </div>
    </Modal>
  )
}

const Box = ({ label, children }) => (
  <div className="rounded-lg border border-edge bg-base p-3"><div className="mb-1 text-xs uppercase tracking-widest text-dim">{label}</div><div className="text-sm">{children}</div></div>
)

// -- changes ------------------------------------------------------------------

const CHANGE_TONE = { proposed: 'var(--color-accent)', applied: 'var(--color-ok)', rejected: 'var(--color-dim)', rolled_back: 'var(--color-run)', failed: 'var(--color-bad)' }

function Changes({ notify }) {
  const [rows, setRows] = useState(null)
  const [filter, setFilter] = useState('')
  const load = () => api.changes(filter || undefined).then(setRows).catch((e) => notify(e.message, true))
  useEffect(() => { load() }, [filter])
  const act = (id, action) => api.changeAction(id, action).then(() => { notify(`${action} done`); load() }).catch((e) => notify(e.message, true))
  if (!rows) return <Spinner />
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <p className="text-sm text-dim">Every write to WordPress passes through here with its before/after. Applied changes roll back with one click.</p>
        <select className={`${field} ml-auto w-40`} value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="">all</option>{Object.keys(CHANGE_TONE).map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </div>
      {rows.length === 0 ? <Empty quip="No changes recorded yet." /> : rows.map((c) => (
        <div key={c.id} className="rounded-lg border border-edge bg-panel p-3 text-xs">
          <div className="flex flex-wrap items-center gap-2">
            <span className="mono" style={{ color: CHANGE_TONE[c.status] }}>{c.status}</span>
            <span className="font-medium">{c.kind}</span>
            <span className="mono text-dim">{c.wp_base}#{c.wp_id} · {c.field} · by {c.source}</span>
            <span className="mono text-dim">{fmtTime(c.created_at)}</span>
            <span className="ml-auto flex gap-2">
              {c.status === 'proposed' && <><button className={btnPrimary} onClick={() => act(c.id, 'apply')}>Apply</button><button className={btnGhost} onClick={() => act(c.id, 'reject')}>Reject</button></>}
              {c.status === 'applied' && <button className={btnGhost} onClick={() => act(c.id, 'rollback')}>Roll back</button>}
            </span>
          </div>
          {c.reason && <p className="mt-1 text-dim">{c.reason}</p>}
          <div className="mt-2 grid gap-2 md:grid-cols-2 mono">
            <div className="rounded bg-base p-2" style={{ color: 'var(--color-bad)' }}>- {String(c.before ?? '').slice(0, 400) || '(empty)'}</div>
            <div className="rounded bg-base p-2" style={{ color: 'var(--color-ok)' }}>+ {String(c.after ?? '').slice(0, 400)}</div>
          </div>
          {c.error && <p className="mt-1" style={{ color: 'var(--color-bad)' }}>{c.error}</p>}
        </div>
      ))}
    </div>
  )
}
