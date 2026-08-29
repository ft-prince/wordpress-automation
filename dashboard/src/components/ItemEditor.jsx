// Universal in-app editor: pages and other content types, one modal.
// When a page's layout is owned by a builder or theme template, the content box
// locks so a save can't wipe the live design; everything else stays editable.
import { useEffect, useState } from 'react'
import { auth, site } from '../api'
import { Badge, btnGhost, btnPrimary, field, Modal, Spinner } from './bits'
import RichEditor from './RichEditor'

const sq = () => (site.current() ? `?site=${site.current()}` : '')
const req = (path, method = 'GET', body) =>
  fetch(path + sq(), {
    method,
    headers: { 'Content-Type': 'application/json', 'X-Auth-Token': auth.token() },
    body: body === undefined ? undefined : JSON.stringify(body),
  }).then((r) => (r.ok ? r.json() : r.json().then((b) => Promise.reject(new Error(b.detail)))))

export default function ItemEditor({ base, itemId, notify, onClose, onSaved }) {
  const [item, setItem] = useState(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    req(`/api/wp/items/${base}/${itemId}`).then(setItem).catch((e) => { notify(e.message, true); onClose() })
  }, [base, itemId])

  if (!item) return <Modal title="Edit" onClose={onClose} wide><Spinner /></Modal>

  const set = (k, v) => setItem((f) => ({ ...f, [k]: v }))
  const descField = item.supports_excerpt ? 'excerpt_raw' : 'meta_desc'

  const save = () => {
    const payload = {
      title: item.title,
      slug: item.slug,
      status: item.status,
    }
    if (item.supports_excerpt) payload.excerpt = item.excerpt_raw
    else payload.meta_desc = item.meta_desc
    if (!item.builder_managed) payload.content = item.content_raw
    setBusy(true)
    req(`/api/wp/items/${base}/${itemId}`, 'PATCH', payload)
      .then(() => { notify('Saved'); onSaved?.(); onClose() })
      .catch((e) => notify(e.message, true))
      .finally(() => setBusy(false))
  }

  return (
    <Modal title={`Edit ${base === 'pages' ? 'page' : 'item'}: ${item.title || '#' + itemId}`} onClose={onClose} wide>
      <div className="space-y-4">
        <div className="flex items-center gap-3 text-sm">
          <Badge status={item.status} />
          {item.link && <a className="text-dim underline-offset-2 hover:underline" href={item.link} target="_blank" rel="noreferrer">View live</a>}
          <a className="text-dim underline-offset-2 hover:underline" href={item.edit_url} target="_blank" rel="noreferrer">Open in WordPress</a>
        </div>

        <label className="block text-sm"><span className="text-dim">Title</span>
          <input className={field} value={item.title} onChange={(e) => set('title', e.target.value)} />
        </label>

        <div className="grid grid-cols-2 gap-4">
          <label className="block text-sm"><span className="text-dim">Slug (URL)</span>
            <input className={`${field} mono`} value={item.slug} onChange={(e) => set('slug', e.target.value)} />
          </label>
          <label className="block text-sm"><span className="text-dim">Status</span>
            <select className={field} value={item.status} onChange={(e) => set('status', e.target.value)}>
              <option value="draft">Draft</option>
              <option value="pending">Awaiting approval</option>
              <option value="publish">Published</option>
            </select>
          </label>
        </div>

        <label className="block text-sm"><span className="text-dim">SEO / meta description</span>
          <textarea className={`${field} h-16`} value={item[descField] || ''}
            onChange={(e) => set(descField, e.target.value)}
            placeholder="This shows up in Google results under your title" />
        </label>

        <div className="block text-sm">
          <span className="text-dim">Content</span>
          {item.builder_managed ? (
            <div className="mt-1 rounded-lg border border-edge bg-base p-4 text-sm text-dim">
              This page's layout is built with a page builder or theme template, so its text
              lives there rather than here. Saving content from this box would blank the live
              design. Use <a className="underline" href={item.edit_url} target="_blank" rel="noreferrer">Open in WordPress</a> for
              layout and text changes. Title, slug, status and the SEO description above all
              save safely from here.
            </div>
          ) : (
            <RichEditor value={item.content_raw} onChange={(v) => set('content_raw', v)} />
          )}
        </div>

        <div className="flex justify-end gap-2 border-t border-edge pt-4">
          <button className={btnGhost} onClick={onClose}>Cancel</button>
          <button className={btnPrimary} onClick={save} disabled={busy || !item.title.trim()}>
            {busy ? 'Saving…' : 'Save changes'}
          </button>
        </div>
      </div>
    </Modal>
  )
}
