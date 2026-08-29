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

      {adding && <AddSite notify={notify} onClose={() => setAdding(false)} onAdded={() => { setAdding(false); load() }} />}
    </div>
  )
}
