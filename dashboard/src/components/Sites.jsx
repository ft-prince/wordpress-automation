// Manage connected WordPress sites: add (with live connection test), switch, remove.
import { useEffect, useState } from 'react'
import { api, site } from '../api'
import { btnGhost, btnPrimary, Empty, field, Modal, Spinner } from './bits'

const slugify = (text) =>
  text.toLowerCase().replace(/https?:\/\//, '').replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 30)

function AddSite({ notify, onClose, onAdded }) {
  const [form, setForm] = useState({ name: '', url: '', user: '', password: '' })
  const [test, setTest] = useState(null) // null | 'testing' | {ok, ...}
  const [busy, setBusy] = useState(false)
  const set = (k, v) => { setForm((f) => ({ ...f, [k]: v })); setTest(null) }

  const runTest = () => {
    setTest('testing')
    api.testSite({ url: form.url, user: form.user, password: form.password })
      .then(setTest)
      .catch((e) => setTest({ ok: false, error: e.message }))
  }

  const save = () => {
    setBusy(true)
    api.addSite({ id: slugify(form.name || form.url), ...form })
      .then((r) => { notify(`Site added. Connected as ${r.connected_as}`); onAdded() })
      .catch((e) => notify(e.message, true))
      .finally(() => setBusy(false))
  }

  return (
    <Modal title="Connect a WordPress site" onClose={onClose}>
      <div className="space-y-3">
        <label className="block text-sm"><span className="text-dim">Site name</span>
          <input className={field} value={form.name} onChange={(e) => set('name', e.target.value)} placeholder="My Other Site" /></label>
        <label className="block text-sm"><span className="text-dim">WordPress URL</span>
          <input className={`${field} mono`} value={form.url} onChange={(e) => set('url', e.target.value)} placeholder="https://example.com" /></label>
        <label className="block text-sm"><span className="text-dim">WP username</span>
          <input className={field} value={form.user} onChange={(e) => set('user', e.target.value)} autoComplete="off" /></label>
        <label className="block text-sm"><span className="text-dim">Application password</span>
          <input type="password" className={`${field} mono`} value={form.password} onChange={(e) => set('password', e.target.value)} autoComplete="off"
            placeholder="from wp-admin → Users → Profile → Application Passwords" /></label>

        {test && test !== 'testing' && (
          <p className="rounded-lg border px-3 py-2 text-sm"
            style={{ borderColor: test.ok ? 'var(--color-ok)' : 'var(--color-bad)', color: test.ok ? 'var(--color-ok)' : 'var(--color-bad)' }}>
            {test.ok ? `✓ connected as ${test.user} (${(test.roles || []).join(', ')})` : `✕ ${test.error}`}
          </p>
        )}

        <div className="flex justify-end gap-2 pt-2">
          <button className={btnGhost} onClick={onClose}>Cancel</button>
          <button className={btnGhost} disabled={!form.url || !form.user || !form.password || test === 'testing'} onClick={runTest}>
            {test === 'testing' ? 'Testing…' : 'Test connection'}
          </button>
          <button className={btnPrimary} disabled={busy || !(test && test.ok)} onClick={save}
            title={!(test && test.ok) ? 'Run a successful connection test first' : undefined}>
            {busy ? 'Adding…' : 'Add site'}
          </button>
        </div>
      </div>
    </Modal>
  )
}

export default function Sites({ notify, onSiteChange }) {
  const [data, setData] = useState(null)
  const [adding, setAdding] = useState(false)
  const load = () => api.sites().then(setData).catch(() => setData({ sites: [] }))
  useEffect(() => { load() }, [])

  if (!data) return <Spinner label="loading sites…" />
  const active = site.current() || data.default

  return (
    <div className="max-w-2xl space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-dim">Each site you connect gets its own posts, SEO checks, pipeline and health view.</p>
        <button className={btnPrimary} onClick={() => setAdding(true)}>+ Connect site</button>
      </div>

      {data.sites.length === 0 ? <Empty quip="No sites connected yet." /> : data.sites.map((s) => (
        <div key={s.id} className="flex items-center gap-4 rounded-xl border bg-panel px-4 py-3"
          style={{ borderColor: s.id === active ? 'var(--color-accent)' : 'var(--color-edge)' }}>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="font-medium">{s.name}</span>
              {s.id === active && <span className="rounded-full px-2 py-0.5 text-xs" style={{ background: 'color-mix(in srgb, var(--color-accent) 15%, transparent)', color: 'var(--color-accent)' }}>active</span>}
              {s.id === data.default && <span className="text-xs text-dim">default</span>}
            </div>
            <div className="text-xs text-dim mono">{s.url} · {s.user}</div>
          </div>
          {s.id !== active && (
            <button className={btnGhost} onClick={() => { site.set(s.id); onSiteChange(); notify(`switched to ${s.name}`) }}>
              Switch to
            </button>
          )}
          <a className={btnGhost} href={`${s.url}/wp-admin/`} target="_blank" rel="noreferrer">wp-admin</a>
          <button className={btnGhost} style={{ color: 'var(--color-bad)' }}
            onClick={() => confirm(`Disconnect "${s.name}"? The WordPress site itself is untouched.`) &&
              api.removeSite(s.id).then(() => { if (site.current() === s.id) site.set(''); notify('site removed'); load(); onSiteChange() }).catch((e) => notify(e.message, true))}>
            Remove
          </button>
        </div>
      ))}

      <GooglePanel notify={notify} sites={data.sites} reload={load} />

      {adding && <AddSite notify={notify} onClose={() => setAdding(false)} onAdded={() => { setAdding(false); load() }} />}
    </div>
  )
}


// -- Google (Search Console + GA4) --------------------------------------------

function GooglePanel({ notify, sites, reload }) {
  const [st, setSt] = useState(null)
  const [props, setProps] = useState(null)
  const [form, setForm] = useState({})
  const load = () => api.googleStatus().then(setSt).catch(() => setSt({ configured: false }))
  useEffect(() => {
    load()
    const q = new URLSearchParams(window.location.search)
    if (q.get('google') === 'connected') notify('Google connected')
    if (q.get('google') === 'error') notify(`Google connection failed: ${q.get('reason')}`, true)
  }, [])
  if (!st) return null
  const connect = () => api.googleAuthUrl().then((r) => { window.location.href = r.url }).catch((e) => notify(e.message, true))
  const loadProps = () => api.googleProperties().then(setProps).catch((e) => notify(e.message, true))
  const save = (s) => api.siteSettings(s.id, form[s.id] || {}).then(() => { notify('saved'); reload() }).catch((e) => notify(e.message, true))
  const set = (id, k, v) => setForm({ ...form, [id]: { ...(form[id] || {}), [k]: v } })
  return (
    <div className="rounded-xl border border-edge bg-panel p-4 text-sm">
      <div className="flex items-center gap-3">
        <div>
          <div className="font-medium">Google Search Console + GA4</div>
          <div className="text-xs text-dim">
            {!st.configured ? 'Add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET on the Secrets page, then connect.'
              : st.connected ? 'Connected. One login covers every site; each site names its own properties.' : 'Client configured - connect your Google account.'}
          </div>
        </div>
        <span className="ml-auto flex gap-2">
          {st.connected && <button className={btnGhost} onClick={loadProps}>List my properties</button>}
          {st.connected ? <button className={btnGhost} onClick={() => api.googleDisconnect().then(load)}>Disconnect</button>
            : <button className={btnPrimary} disabled={!st.configured} onClick={connect}>Connect Google</button>}
        </span>
      </div>
      {props && (
        <div className="mt-3 grid gap-2 text-xs mono md:grid-cols-2">
          <div><div className="text-dim">Search Console properties</div>{props.gsc.map((p) => <div key={p}>{p}</div>)}</div>
          <div><div className="text-dim">GA4 properties</div>{props.ga4.length ? props.ga4.map((p) => <div key={p.id}>{p.id} · {p.name}</div>) : <div className="text-dim">(grant not available - type the id from GA4 admin)</div>}</div>
        </div>
      )}
      {st.configured && sites.map((s) => (
        <div key={s.id} className="mt-3 grid items-end gap-2 md:grid-cols-[1fr_1fr_1fr_auto]">
          <label className="text-xs text-dim">{s.name} · GSC property<input className={`${field} mt-1 mono`} placeholder="sc-domain:example.com or https://example.com/" defaultValue={s.gsc_property} onChange={(e) => set(s.id, 'gsc_property', e.target.value)} /></label>
          <label className="text-xs text-dim">GA4 property id<input className={`${field} mt-1 mono`} placeholder="123456789" defaultValue={s.ga4_property} onChange={(e) => set(s.id, 'ga4_property', e.target.value)} /></label>
          <label className="text-xs text-dim">Country / language<input className={`${field} mt-1 mono`} placeholder="IN / en" defaultValue={[s.country, s.language].filter(Boolean).join(' / ')} onChange={(e) => { const [c, l] = e.target.value.split('/').map((x) => x.trim()); set(s.id, 'country', c || ''); set(s.id, 'language', l || '') }} /></label>
          <button className={btnGhost} onClick={() => save(s)}>Save</button>
        </div>
      ))}
    </div>
  )
}
