// Theme file editor: full CRUD on the active theme's files, per site.
// Saves are syntax-checked server-side; the previous version is backed up first.
import { useEffect, useState } from 'react'
import { auth, site } from '../api'
import { btnGhost, btnPrimary, Empty, field, Spinner } from './bits'

const sq = (sep = '?') => (site.current() ? `${sep}site=${site.current()}` : '')
const req = (path, method = 'GET', body) =>
  fetch(path, {
    method,
    headers: { 'Content-Type': 'application/json', 'X-Auth-Token': auth.token() },
    body: body === undefined ? undefined : JSON.stringify(body),
  }).then((r) => (r.ok ? r.json() : r.json().then((b) => Promise.reject(new Error(b.detail || (b.message ?? 'failed'))))))

export default function ThemeFiles({ notify }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [open, setOpen] = useState(null)      // { path, content, originalContent }
  const [busy, setBusy] = useState(false)
  const [newPath, setNewPath] = useState('')
  const [filter, setFilter] = useState('')

  const load = () => req(`/api/theme/files${sq()}`).then((d) => { setData(d); setError(null) }).catch((e) => setError(e.message))
  useEffect(() => { load() }, [])

  const openFile = (path) => {
    setBusy(true)
    req(`/api/theme/file?path=${encodeURIComponent(path)}${sq('&')}`)
      .then((f) => setOpen({ path, content: f.content, originalContent: f.content }))
      .catch((e) => notify(e.message, true))
      .finally(() => setBusy(false))
  }

  const save = () => {
    setBusy(true)
    req(`/api/theme/file${sq()}`, 'POST', { path: open.path, content: open.content })
      .then(() => { notify(`Saved ${open.path}. Previous version backed up.`); setOpen({ ...open, originalContent: open.content }); load() })
      .catch((e) => notify(e.message, true))
      .finally(() => setBusy(false))
  }

  const removeFile = (path) => {
    if (!confirm(`Delete ${path} from the live theme? A backup is kept in uploads/automation-backups.`)) return
    req(`/api/theme/file?path=${encodeURIComponent(path)}${sq('&')}`, 'DELETE')
      .then(() => { notify('Deleted, backup kept'); if (open?.path === path) setOpen(null); load() })
      .catch((e) => notify(e.message, true))
  }

  const createFile = () => {
    const path = newPath.trim()
    if (!path) return
    setBusy(true)
    req(`/api/theme/file${sq()}`, 'POST', { path, content: path.endsWith('.php') ? '<?php\n' : '' })
      .then(() => { notify(`Created ${path}`); setNewPath(''); load(); openFile(path) })
      .catch((e) => notify(e.message, true))
      .finally(() => setBusy(false))
  }

  if (error) return (
    <div className="max-w-xl rounded-lg border px-4 py-3 text-sm" style={{ borderColor: 'var(--color-bad)', color: 'var(--color-bad)' }}>
      {error} — <button className="underline" onClick={load}>retry</button>
    </div>
  )
  if (!data) return <Spinner label="Loading theme files…" />

  const dirty = open && open.content !== open.originalContent
  const files = data.files.filter((f) => !filter || f.path.toLowerCase().includes(filter.toLowerCase()))

  return (
    <div className="flex gap-5">
      {/* file list */}
      <div className="w-72 shrink-0 space-y-3">
        <div>
          <p className="text-sm text-dim">Active theme: <span className="mono text-ink">{data.theme}</span></p>
          <p className="mt-1 text-xs text-dim">PHP saves are syntax-checked first, and every save or delete keeps a backup on the server.</p>
        </div>
        <input className={field} placeholder="Filter files…" value={filter} onChange={(e) => setFilter(e.target.value)} />
        <div className="max-h-[55vh] space-y-0.5 overflow-y-auto rounded-lg border border-edge bg-panel p-1.5">
          {files.length === 0 ? <Empty quip="No files match." /> : files.map((f) => (
            <div key={f.path} className={`group flex items-center gap-2 rounded-md px-2 py-1.5 text-xs mono ${open?.path === f.path ? 'bg-edge text-ink' : 'text-dim hover:text-ink'}`}>
              <button className="min-w-0 flex-1 truncate text-left" title={f.path} onClick={() => openFile(f.path)}>{f.path}</button>
              <span className="text-dim">{(f.size / 1024).toFixed(1)}k</span>
              <button className="hidden text-xs group-hover:block" style={{ color: 'var(--color-bad)' }}
                aria-label={`Delete ${f.path}`} onClick={() => removeFile(f.path)}>✕</button>
            </div>
          ))}
        </div>
        <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); createFile() }}>
          <input className={`${field} mono text-xs`} placeholder="new-file.php or css/extra.css"
            value={newPath} onChange={(e) => setNewPath(e.target.value)} />
          <button type="submit" className={btnGhost} disabled={!newPath.trim() || busy}>Create</button>
        </form>
      </div>

      {/* editor */}
      <div className="min-w-0 flex-1">
        {!open ? (
          <Empty quip="Pick a file on the left to view or edit it." />
        ) : (
          <div className="space-y-3">
            <div className="flex items-center gap-3">
              <h2 className="mono text-sm font-bold">{open.path}</h2>
              {dirty && <span className="text-xs" style={{ color: 'var(--color-accent)' }}>unsaved changes</span>}
              <span className="ml-auto flex gap-2">
                <button className={btnGhost} disabled={!dirty}
                  onClick={() => setOpen({ ...open, content: open.originalContent })}>Discard</button>
                <button className={btnPrimary} disabled={!dirty || busy} onClick={save}>
                  {busy ? 'Saving…' : 'Save to live site'}
                </button>
              </span>
            </div>
            <textarea
              className="h-[65vh] w-full resize-none rounded-lg border border-edge bg-base p-4 text-xs mono outline-none focus:border-accent"
              spellCheck={false}
              value={open.content}
              onChange={(e) => setOpen({ ...open, content: e.target.value })}
              aria-label={`Contents of ${open.path}`}
            />
          </div>
        )}
      </div>
    </div>
  )
}
