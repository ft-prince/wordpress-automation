import { useEffect, useState } from 'react'
import { api } from '../api'
import { Empty, fmtTime } from './bits'

export function Secrets({ notify }) {
  const [items, setItems] = useState([])
  const [editing, setEditing] = useState(null)
  const [value, setValue] = useState('')

  const load = () => api.secrets().then(setItems).catch(() => {})
  useEffect(() => { load() }, [])

  const save = (key) =>
    api.setSecret(key, value)
      .then(() => { notify(`${key} updated`); setEditing(null); setValue(''); load() })
      .catch((e) => notify(e.message, true))

  return (
    <div className="max-w-2xl space-y-2">
      {items.map((s) => (
        <div key={s.key} className="rounded-lg border border-edge bg-panel px-4 py-3">
          <div className="flex items-center gap-4">
            <span className="mono text-sm font-medium">{s.key}</span>
            <span className="mono text-sm text-dim">{s.value}</span>
            {s.used_by.length > 0 && (
              <span className="text-xs text-dim">used by {s.used_by.join(', ')}</span>
            )}
            <button onClick={() => { setEditing(editing === s.key ? null : s.key); setValue('') }} className="ml-auto rounded border border-edge px-2 py-1 text-xs hover:border-accent">
              {editing === s.key ? 'Cancel' : 'Rotate'}
            </button>
          </div>
          {editing === s.key && (
            <div className="mt-3 flex gap-2">
              <input
                type="password"
                value={value}
                onChange={(e) => setValue(e.target.value)}
                placeholder="New value (hidden after saving)"
                className="flex-1 rounded-lg border border-edge bg-base px-3 py-2 text-sm mono outline-none focus:border-accent"
              />
              <button onClick={() => save(s.key)} disabled={!value} className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-black disabled:opacity-40">
                Save
              </button>
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

export function Audit() {
  const [rows, setRows] = useState([])
  useEffect(() => { api.audit().then(setRows).catch(() => {}) }, [])
  if (rows.length === 0) return <Empty quip="No changes yet. History starts when you touch something." />
  return (
    <div className="max-w-3xl space-y-1.5">
      {rows.map((r) => (
        <div key={r.id} className="rounded-lg border border-edge bg-panel px-4 py-2.5 text-sm mono">
          <span className="text-dim">{fmtTime(r.ts)}</span>{' '}
          <span className="text-accent">{r.actor}</span> {r.action}{' '}
          <span className="font-medium">{r.target}</span>
          {r.before && r.after && (
            <div className="mt-1 text-xs text-dim">
              <span style={{ color: 'var(--color-bad)' }}>- {r.before}</span>
              <br />
              <span style={{ color: 'var(--color-ok)' }}>+ {r.after}</span>
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
