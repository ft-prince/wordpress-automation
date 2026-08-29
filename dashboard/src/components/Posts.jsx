// WordPress posts: full CRUD. Status tabs, search, bulk bar, editor drawer with AI generate.
import { useEffect, useMemo, useState } from 'react'
import { api, site } from '../api'
import { Badge, btnGhost, btnPrimary, CopyBtn, Empty, field, fmtTime, Modal, Spinner } from './bits'
import RichEditor, { SeoPanel } from './RichEditor'
import SeoChip from './SeoChip'

const TABS = [
  ['publish', 'Published'], ['future', 'Scheduled'], ['pending', 'Approval'],
  ['draft', 'Drafts'], ['trash', 'Trash'],
]

function Thumb({ src }) {
  return src ? (
    <img src={src} alt="" className="h-9 w-14 rounded object-cover" />
  ) : (
    <span className="flex h-9 w-14 items-center justify-center rounded bg-edge text-dim">
      <svg viewBox="0 0 24 24" className="h-4 w-4"><path d="M4 5h16v14H4zm3 10 3-4 2 2 3-5 5 7" fill="none" stroke="currentColor" strokeWidth="1.5" /></svg>
    </span>
  )
}

// ── Editor drawer ──────────────────────────────────────────────────────────
function PostEditor({ postId, terms, notify, onClose, onSaved }) {
  const isNew = postId === 'new'
  const [form, setForm] = useState(null)
  const [busy, setBusy] = useState('')
  const [topic, setTopic] = useState('')
  const [imgUrl, setImgUrl] = useState('')
  const [kw, setKw] = useState(null)
  const [revs, setRevs] = useState(null)

  useEffect(() => {
    if (isNew) {
      setForm({ title: '', content_raw: '', excerpt_raw: '', slug: '', status: 'draft', date_gmt: '', category_ids: [], featured_image: null })
    } else {
      api.post(postId).then(setForm).catch((e) => notify(e.message, true))
    }
  }, [postId])

  if (!form) return <Modal title="Edit post" onClose={onClose} wide><Spinner /></Modal>

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }))

  const generate = () => {
    if (!topic.trim()) return notify('enter a topic first', true)
    setBusy('generating')
    api.generate(topic)
      .then((r) => { setForm((f) => ({ ...f, title: r.title, content_raw: r.content, excerpt_raw: r.excerpt || f.excerpt_raw })); setKw(r.keywords || null); notify('Draft ready. Give it a read before saving') })
      .catch((e) => notify(e.message, true))
      .finally(() => setBusy(''))
  }

  const save = () => {
    const payload = {
      title: form.title, content: form.content_raw, excerpt: form.excerpt_raw,
      status: form.status, categories: form.category_ids,
    }
    if (form.slug) payload.slug = form.slug
    if (form.status === 'future') {
      if (!form.date_gmt) return notify('scheduled posts need a date', true)
      payload.date_gmt = form.date_gmt
    }
    setBusy('saving')
    const req = isNew ? api.createPost(payload) : api.updatePost(postId, payload)
    req
      .then(async (saved) => {
        if (imgUrl.trim()) {
          await api.setFeatured(saved.id, imgUrl.trim()).then(() => notify('featured image set')).catch((e) => notify(`image failed: ${e.message}`, true))
        }
        notify(isNew ? `created "${saved.title}"` : 'post saved')
        onSaved()
      })
      .catch((e) => notify(e.message, true))
      .finally(() => setBusy(''))
  }

  return (
    <Modal title={isNew ? 'New post' : `Edit #${postId}`} onClose={onClose} wide>
      <div className="space-y-4">
        {isNew && (
          <div className="flex gap-2 rounded-lg border border-accent/40 bg-base p-3">
            <input className={field} placeholder="What should this post be about?" value={topic} onChange={(e) => setTopic(e.target.value)} />
            <button className={btnPrimary} onClick={generate} disabled={busy === 'generating'}>
              {busy === 'generating' ? 'Researching…' : 'Generate'}
            </button>
          </div>
        )}
        {kw && (
          <p className="rounded-lg bg-edge/30 px-3 py-2 text-xs mono">
            <span className="text-dim">targeting</span>{' '}
            <span style={{ color: 'var(--color-accent)' }}>{kw.primary}</span>
            {kw.secondary?.length > 0 && <span className="text-dim"> · {kw.secondary.join(' · ')}</span>}
          </p>
        )}

        <label className="block text-sm"><span className="text-dim">Title</span>
          <input className={field} value={form.title} onChange={(e) => set('title', e.target.value)} />
        </label>

        <div className="block text-sm"><span className="text-dim">Content</span>
          <RichEditor value={form.content_raw} onChange={(v) => set('content_raw', v)} />
        </div>

        <SeoPanel form={form} />

        <div className="grid grid-cols-2 gap-4">
          <label className="block text-sm"><span className="text-dim">Status</span>
            <select className={field} value={form.status === 'trash' ? 'draft' : form.status} onChange={(e) => set('status', e.target.value)}>
              <option value="draft">Draft</option>
              <option value="pending">Awaiting approval</option>
              <option value="future">Scheduled</option>
              <option value="publish">Published</option>
            </select>
          </label>
          {form.status === 'future' && (
            <label className="block text-sm"><span className="text-dim">Publish at (UTC)</span>
              <input type="datetime-local" className={field} value={(form.date_gmt || '').slice(0, 16)} onChange={(e) => set('date_gmt', e.target.value + ':00')} />
            </label>
          )}
          <label className="block text-sm"><span className="text-dim">Category</span>
            <select className={field} value={form.category_ids[0] || ''} onChange={(e) => set('category_ids', e.target.value ? [Number(e.target.value)] : [])}>
              <option value="">None</option>
              {terms.categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </label>
          <label className="block text-sm"><span className="text-dim">Slug (URL)</span>
            <input className={`${field} mono`} value={form.slug || ''} onChange={(e) => set('slug', e.target.value)} placeholder="auto from title" />
          </label>
        </div>

        <label className="block text-sm"><span className="text-dim">SEO / meta description (excerpt)</span>
          <textarea className={`${field} h-16`} value={form.excerpt_raw} onChange={(e) => set('excerpt_raw', e.target.value)} placeholder="This shows up in Google results under your title" />
        </label>

        <label className="block text-sm"><span className="text-dim">Featured image URL {form.featured_image && '(set. Paste a URL to replace it)'}</span>
          <div className="flex items-center gap-2">
            {form.featured_image && <Thumb src={form.featured_image} />}
            <input className={field} value={imgUrl} onChange={(e) => setImgUrl(e.target.value)} placeholder="Paste an image URL, or use the button to find one" />
            {!isNew && (
              <button type="button" className={btnGhost} disabled={busy === 'image'} onClick={() => {
                setBusy('image')
                fetch(`/api/wp/posts/${postId}/featured/generate${site.current() ? `?site=${site.current()}` : ''}`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Auth-Token': localStorage.getItem('dash_token') || '' }, body: JSON.stringify({}) })
                  .then((r) => (r.ok ? r.json() : r.json().then((b) => Promise.reject(new Error(b.detail)))))
                  .then(() => { notify('AI image generated & attached'); api.post(postId).then(setForm) })
                  .catch((e) => notify(e.message, true))
                  .finally(() => setBusy(''))
              }}>
                {busy === 'image' ? 'Painting…' : 'Find image'}
              </button>
            )}
          </div>
        </label>

        {!isNew && (
          <div className="text-xs text-dim">
            <button className="underline-offset-2 hover:underline" onClick={() => api.revisions(postId).then(setRevs).catch(() => setRevs([]))}>
              View revision history
            </button>
            {revs && (revs.length === 0
              ? <span className="ml-2">no revisions recorded</span>
              : <ul className="mt-1 space-y-0.5">{revs.map((r) => <li key={r.id} className="mono">#{r.id} · {fmtTime(r.modified + 'Z')}</li>)}</ul>
            )}
          </div>
        )}

        <div className="flex justify-end gap-2 border-t border-edge pt-4">
          <button className={btnGhost} onClick={onClose}>Cancel</button>
          <button className={btnPrimary} onClick={save} disabled={busy === 'saving' || !form.title.trim()}>
            {busy === 'saving' ? 'Saving…' : isNew ? 'Create post' : 'Save changes'}
          </button>
        </div>
      </div>
    </Modal>
  )
}

// ── Posts page ─────────────────────────────────────────────────────────────
export default function Posts({ notify }) {
  const [tab, setTab] = useState('publish')
  const [posts, setPosts] = useState(null)
  const [counts, setCounts] = useState({})
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('')
  const [selected, setSelected] = useState(new Set())
  const [editing, setEditing] = useState(null)
  const [terms, setTerms] = useState({ categories: [], tags: [] })
  const [error, setError] = useState(null)

  const load = () => {
    const params = { status: tab, limit: 50 }
    if (search) params.search = search
    if (category) params.category = category
    api.posts(params).then((p) => { setPosts(p); setError(null) }).catch((e) => { setError(e.message); setPosts([]) })
    api.overview().then((o) => setCounts({ publish: o.published, future: o.scheduled, draft: o.drafts, pending: o.pending_approval })).catch(() => {})
  }
  useEffect(() => { setPosts(null); setSelected(new Set()); load() }, [tab, category])
  useEffect(() => { const t = setTimeout(load, 350); return () => clearTimeout(t) }, [search])

  const toggle = (id) => setSelected((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })
  const allIds = useMemo(() => (posts || []).map((p) => p.id), [posts])

  useEffect(() => { api.terms().then(setTerms).catch(() => {}) }, [])

  const doBulk = (action, value) => {
    const label = { publish: 'publish', trash: 'move to trash', delete: 'permanently delete', restore: 'restore', approve: 'send to approval' }[action] || action
    if (['delete', 'trash', 'publish'].includes(action) && !confirm(`${label} ${selected.size} post(s)?`)) return
    api.bulk([...selected], action, value)
      .then((r) => { notify(`${r.ok} ok${r.failed ? `, ${r.failed} failed` : ''}`); setSelected(new Set()); load() })
      .catch((e) => notify(e.message, true))
  }

  const rowAction = (fn, msg) => fn.then(() => { notify(msg); load() }).catch((e) => notify(e.message, true))

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <nav className="flex gap-1 rounded-lg border border-edge bg-panel p-1" role="tablist">
          {TABS.map(([key, label]) => (
            <button key={key} role="tab" aria-selected={tab === key} onClick={() => setTab(key)}
              className={`rounded-md px-3 py-1.5 text-sm ${tab === key ? 'bg-edge text-ink' : 'text-dim hover:text-ink'}`}>
              {label}{counts[key] != null && <span className="ml-1.5 text-xs text-dim mono">{counts[key]}</span>}
            </button>
          ))}
        </nav>
        <input className={`${field} !w-56`} placeholder="Search posts…" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search posts" />
        <select className={`${field} !w-44`} value={category} onChange={(e) => setCategory(e.target.value)} aria-label="Filter by category">
          <option value="">All categories</option>
          {terms.categories.map((c) => <option key={c.id} value={c.id}>{c.name} ({c.count})</option>)}
        </select>
        <button className={`${btnPrimary} ml-auto`} onClick={() => setEditing('new')}>+ New post</button>
      </div>

      {selected.size > 0 && (
        <div className="log-line flex flex-wrap items-center gap-2 rounded-lg border border-accent/50 bg-panel px-4 py-2.5 text-sm">
          <span className="mono text-accent">{selected.size} selected</span>
          {tab !== 'publish' && tab !== 'trash' && <button className={btnGhost} onClick={() => doBulk('publish')}>Publish</button>}
          {tab === 'draft' && <button className={btnGhost} onClick={() => doBulk('approve')}>Send to approval</button>}
          {tab !== 'trash' && (
            <select className={`${field} !w-52`} defaultValue="" onChange={(e) => { if (e.target.value) doBulk('category', e.target.value); e.target.value = '' }} aria-label="Bulk set category">
              <option value="" disabled>Set category…</option>
              {terms.categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          )}
          {tab === 'trash'
            ? <>
                <button className={btnGhost} onClick={() => doBulk('restore')}>Restore</button>
                <button className={btnGhost} style={{ color: 'var(--color-bad)' }} onClick={() => doBulk('delete')}>Delete forever</button>
              </>
            : <button className={btnGhost} onClick={() => doBulk('trash')}>Move to trash</button>}
          <button className="ml-auto text-xs text-dim hover:text-ink" onClick={() => setSelected(new Set())}>clear</button>
        </div>
      )}

      {error && (
        <div className="rounded-lg border px-4 py-3 text-sm" style={{ borderColor: 'var(--color-bad)', color: 'var(--color-bad)' }}>
          WordPress unreachable: {error} — <button className="underline" onClick={load}>retry</button>
        </div>
      )}

      {posts === null ? <Spinner label="loading posts…" /> : posts.length === 0 ? (
        <Empty quip={search ? 'No posts match your search.' : tab === 'trash' ? 'Trash is empty.' : 'Nothing here yet.'} />
      ) : (
        <div className="overflow-x-auto rounded-xl border border-edge">
          <table className="w-full bg-panel text-sm">
            <thead>
              <tr className="border-b border-edge text-left text-xs uppercase tracking-wider text-dim">
                <th className="px-3 py-3"><input type="checkbox" aria-label="Select all" checked={selected.size === allIds.length && allIds.length > 0} onChange={(e) => setSelected(e.target.checked ? new Set(allIds) : new Set())} /></th>
                <th className="px-2 py-3 font-normal"></th>
                <th className="px-3 py-3 font-normal">title</th>
                <th className="px-3 py-3 font-normal">status</th>
                <th className="px-3 py-3 font-normal">{tab === 'future' ? 'publishes' : 'date'}</th>
                <th className="px-3 py-3 font-normal">category</th>
                <th className="px-3 py-3 font-normal">urls</th>
                <th className="px-3 py-3 font-normal">actions</th>
              </tr>
            </thead>
            <tbody>
              {posts.map((p) => (
                <tr key={p.id} className="border-b border-edge/50 last:border-0 hover:bg-edge/20">
                  <td className="px-3 py-2.5"><input type="checkbox" aria-label={`Select ${p.title}`} checked={selected.has(p.id)} onChange={() => toggle(p.id)} /></td>
                  <td className="px-2 py-2.5"><Thumb src={p.featured_image} /></td>
                  <td className="px-3 py-2.5 max-w-64">
                    <button className="truncate block font-medium underline-offset-2 hover:underline text-left" onClick={() => setEditing(p.id)} title={p.title}>{p.title}</button>
                    <span className="text-xs text-dim mono">#{p.id} · {p.author}</span>
                  </td>
                  <td className="px-3 py-2.5"><span className="flex flex-col items-start gap-1"><Badge status={p.status} /><SeoChip seo={p.seo} /></span></td>
                  <td className="px-3 py-2.5 mono text-dim text-xs">{fmtTime(p.date_gmt && p.date_gmt + 'Z')}</td>
                  <td className="px-3 py-2.5 text-dim text-xs">{p.categories.join(', ') || '—'}</td>
                  <td className="px-3 py-2.5">
                    <span className="flex items-center gap-1.5 text-xs">
                      <a className="text-dim hover:text-ink underline-offset-2 hover:underline" href={p.status === 'publish' ? p.link : p.preview_url} target="_blank" rel="noreferrer">
                        {p.status === 'publish' ? 'Live' : 'Preview'}
                      </a>
                      <CopyBtn text={p.status === 'publish' ? p.link : p.preview_url} notify={notify} />
                      <a className="text-dim hover:text-ink underline-offset-2 hover:underline" href={p.edit_url} target="_blank" rel="noreferrer">WP</a>
                    </span>
                  </td>
                  <td className="px-3 py-2.5">
                    <span className="flex gap-1.5 text-xs">
                      {p.status !== 'publish' && p.status !== 'trash' && (
                        <button className={btnGhost} onClick={() => confirm(`Publish "${p.title}" now?`) && rowAction(api.updatePost(p.id, { status: 'publish' }), 'published')}>Publish</button>
                      )}
                      {p.status === 'trash'
                        ? <>
                            <button className={btnGhost} onClick={() => rowAction(api.restorePost(p.id), 'restored to drafts')}>Restore</button>
                            <button className={btnGhost} style={{ color: 'var(--color-bad)' }} onClick={() => confirm('Permanently delete? This cannot be undone.') && rowAction(api.deletePost(p.id, true), 'deleted forever')}>Delete</button>
                          </>
                        : <button className={btnGhost} onClick={() => rowAction(api.deletePost(p.id), 'moved to trash')}>Trash</button>}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {editing && (
        <PostEditor postId={editing} terms={terms} notify={notify} onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); load() }} />
      )}
    </div>
  )
}
