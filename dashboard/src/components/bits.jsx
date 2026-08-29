import { useState } from 'react'
// Shared atoms: status dots, tag glyphs, illustrated empty/failure states.
// Status is never color-alone — every dot pairs with a label.

export const STATUS = {
  running: { color: 'var(--color-run)', label: 'running' },
  success: { color: 'var(--color-ok)', label: 'success' },
  failed: { color: 'var(--color-bad)', label: 'failed' },
  timeout: { color: 'var(--color-bad)', label: 'timeout' },
  killed: { color: 'var(--color-pause)', label: 'killed' },
  paused: { color: 'var(--color-pause)', label: 'paused' },
  never: { color: 'var(--color-pause)', label: 'never ran' },
  // WordPress post statuses
  publish: { color: 'var(--color-ok)', label: 'published' },
  future: { color: 'var(--color-run)', label: 'scheduled' },
  draft: { color: 'var(--color-pause)', label: 'draft' },
  pending: { color: 'var(--color-accent)', label: 'awaiting approval' },
  trash: { color: 'var(--color-bad)', label: 'trashed' },
}

export function Badge({ status }) {
  const s = STATUS[status] || STATUS.never
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs mono"
      style={{ color: s.color, background: `color-mix(in srgb, ${s.color} 12%, transparent)`, border: `1px solid color-mix(in srgb, ${s.color} 35%, transparent)` }}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${status === 'running' ? 'dot-running' : ''}`} style={{ background: s.color }} />
      {s.label}
    </span>
  )
}

export function Spinner({ label = 'loading…' }) {
  return (
    <div className="flex items-center gap-2 py-8 justify-center text-dim text-sm" role="status">
      <svg viewBox="0 0 24 24" className="h-4 w-4 animate-spin"><circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeWidth="2.5" strokeDasharray="42" strokeDashoffset="12" strokeLinecap="round" /></svg>
      {label}
    </div>
  )
}

export function CopyBtn({ text, notify }) {
  return (
    <button
      onClick={() => navigator.clipboard.writeText(text).then(() => notify?.('copied to clipboard'))}
      title={`Copy ${text}`}
      aria-label="Copy URL"
      className="rounded border border-edge px-1.5 py-0.5 text-xs text-dim hover:border-accent hover:text-ink"
    >⧉</button>
  )
}

export function Modal({ title, onClose, children, wide }) {
  return (
    <div className="fixed inset-0 z-40 flex items-start justify-center overflow-y-auto bg-black/60 p-6" onClick={onClose}>
      <div
        className={`log-line w-full ${wide ? 'max-w-3xl' : 'max-w-lg'} rounded-xl border border-edge bg-panel p-6 shadow-2xl`}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label={title}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-bold">{title}</h2>
          <button onClick={onClose} aria-label="Close" className="rounded px-2 py-1 text-dim hover:text-ink">✕</button>
        </div>
        {children}
      </div>
    </div>
  )
}

export const field = 'w-full rounded-lg border border-edge bg-base px-3 py-2 text-sm outline-none focus:border-accent'

export const SCHEDULE_PRESETS = [
  ['manual', 'Manual only (run from dashboard)'],
  ['0 9 * * 1,4', 'Mon and Thu at 9:00 UTC'],
  ['0 9 * * 1,3,5', 'Mon, Wed and Fri at 9:00'],
  ['0 9 * * 1-5', 'Every weekday, 9:00'],
  ['0 9 * * *', 'Every day, 9:00'],
  ['0 9 * * 1', 'Every Monday at 9:00'],
  ['0 9 1 * *', 'Monthly on the 1st at 9:00'],
  ['custom', 'Custom cron…'],
]

export function ScheduleField({ value, onChange }) {
  const isPreset = SCHEDULE_PRESETS.some(([v]) => v === value && v !== 'custom')
  const [custom, setCustom] = useState(!isPreset && value !== 'manual')
  return (
    <div>
      <select
        className={field}
        value={custom ? 'custom' : value}
        onChange={(e) => {
          if (e.target.value === 'custom') setCustom(true)
          else { setCustom(false); onChange(e.target.value) }
        }}
        aria-label="Schedule"
      >
        {SCHEDULE_PRESETS.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
      </select>
      {custom && (
        <input className={`${field} mono mt-1.5`} value={value} onChange={(e) => onChange(e.target.value)}
          placeholder="cron: min hour day month weekday" aria-label="Custom cron expression" />
      )}
      <span className="mt-1 block text-xs text-accent">{humanCron(value)}</span>
    </div>
  )
}

export const PUBLISH_POLICIES = [
  ['draft', 'Save as draft, I publish myself', 'safest'],
  ['seo80', 'Publish automatically if the SEO score is 80 or higher', 'balanced'],
  ['publish', 'Always publish immediately', 'hands-off'],
]

export function PolicyField({ value, onChange }) {
  return (
    <div>
      <select className={field} value={value || 'draft'} onChange={(e) => onChange(e.target.value)} aria-label="Publish policy">
        {PUBLISH_POLICIES.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
      </select>
      <span className="mt-1 block text-xs text-dim">
        {value === 'publish' ? 'Posts go live without review. We suggest trying the SEO option first.'
          : value === 'seo80' ? 'Uses the same checks you see in the SEO panel.'
          : 'Every post waits in Drafts until you publish it.'}
      </span>
    </div>
  )
}
export const btnPrimary = 'rounded-lg bg-accent px-4 py-2 text-sm font-medium text-black disabled:opacity-40'
export const btnGhost = 'rounded-lg border border-edge px-3 py-1.5 text-sm hover:border-accent disabled:opacity-40'

export function Dot({ status }) {
  const s = STATUS[status] || STATUS.never
  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        className={`inline-block h-2 w-2 rounded-full ${status === 'running' ? 'dot-running' : ''}`}
        style={{ background: s.color }}
      />
      <span className="text-xs mono" style={{ color: s.color }}>{s.label}</span>
    </span>
  )
}

// Custom inline SVG glyphs per tag — not stock icons.
const GLYPHS = {
  content: (
    <path d="M4 5h16v2H4zm0 4h16v2H4zm0 4h10v2H4zm0 4h7v2H4z" fill="currentColor" />
  ),
  wordpress: (
    <>
      <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeWidth="1.6" />
      <path d="M5.5 9.5 9 18.5l2-6m1.5-3L16 18.5l2.5-9" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
    </>
  ),
  vision: (
    <>
      <rect x="3" y="6" width="18" height="13" rx="2" fill="none" stroke="currentColor" strokeWidth="1.6" />
      <circle cx="12" cy="12.5" r="3.5" fill="none" stroke="currentColor" strokeWidth="1.6" />
      <path d="M8 6 9.5 3.5h5L16 6" fill="none" stroke="currentColor" strokeWidth="1.6" />
    </>
  ),
  default: (
    <>
      <rect x="4" y="4" width="16" height="16" rx="3" fill="none" stroke="currentColor" strokeWidth="1.6" />
      <path d="M9 12h6M12 9v6" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </>
  ),
}

export function TagGlyph({ tag }) {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4 shrink-0" aria-hidden="true">
      {GLYPHS[tag] || GLYPHS.default}
    </svg>
  )
}

export function Tag({ name }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-edge px-2 py-0.5 text-xs text-dim">
      <TagGlyph tag={name} />
      {name}
    </span>
  )
}

// Illustrated empty state with a one-line quip.
export function Empty({ quip }) {
  return (
    <div className="flex flex-col items-center gap-3 py-16 text-dim">
      <svg viewBox="0 0 80 60" className="h-16 w-24" aria-hidden="true">
        <ellipse cx="40" cy="52" rx="26" ry="4" fill="var(--color-edge)" />
        <rect x="22" y="14" width="36" height="26" rx="4" fill="none" stroke="var(--color-dim)" strokeWidth="2" />
        <path d="M30 27h8m4 0h8" stroke="var(--color-dim)" strokeWidth="2" strokeLinecap="round" />
        <path d="M34 34c2 2 10 2 12 0" fill="none" stroke="var(--color-dim)" strokeWidth="2" strokeLinecap="round" />
        <circle cx="62" cy="12" r="5" fill="none" stroke="var(--color-accent)" strokeWidth="2" strokeDasharray="3 2" />
      </svg>
      <p className="text-sm">{quip}</p>
    </div>
  )
}

// Failures get a distinct illustrated state — never just red text.
export function FailureArt() {
  return (
    <svg viewBox="0 0 80 60" className="h-14 w-20" aria-hidden="true">
      <ellipse cx="40" cy="54" rx="24" ry="3" fill="var(--color-edge)" />
      <path d="M40 8 62 48H18z" fill="none" stroke="var(--color-bad)" strokeWidth="2.5" strokeLinejoin="round" />
      <path d="M40 22v13" stroke="var(--color-bad)" strokeWidth="2.5" strokeLinecap="round" />
      <circle cx="40" cy="41" r="1.8" fill="var(--color-bad)" />
      <path d="M14 18c3-1 4-4 4-4s1 3 4 4c-3 1-4 4-4 4s-1-3-4-4z" fill="var(--color-bad)" opacity="0.5" />
    </svg>
  )
}

export function humanCron(expr) {
  if (!expr || expr === 'manual') return 'manual'
  const [min, hour, dom, , dow] = expr.split(/\s+/)
  const days = { 0: 'Sun', 1: 'Mon', 2: 'Tue', 3: 'Wed', 4: 'Thu', 5: 'Fri', 6: 'Sat' }
  if (min.startsWith('*/')) return `every ${min.slice(2)} min`
  if (hour !== '*' && dow !== '*' && dow !== undefined) {
    const names = dow.split(',').map((d) => days[d] || d).join(', ')
    return `${names} at ${hour.padStart(2, '0')}:${min.padStart(2, '0')} UTC`
  }
  if (hour !== '*' && dom === '*') return `daily at ${hour.padStart(2, '0')}:${min.padStart(2, '0')} UTC`
  return expr
}

export const fmtMs = (ms) =>
  ms == null ? '—' : ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`

export const fmtTime = (iso) => (iso ? new Date(iso).toLocaleString() : '—')

export function Sparkline({ values }) {
  if (!values?.length) return <span className="text-dim text-xs">no runs yet</span>
  const max = Math.max(...values, 1)
  const pts = values.map((v, i) => `${(i / Math.max(values.length - 1, 1)) * 100},${30 - (v / max) * 26}`)
  return (
    <svg viewBox="0 0 100 32" className="h-8 w-40" preserveAspectRatio="none" aria-label="duration trend">
      <polyline points={pts.join(' ')} fill="none" stroke="var(--color-accent)" strokeWidth="1.5" />
    </svg>
  )
}
