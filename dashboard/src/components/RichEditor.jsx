// Minimal WYSIWYG on contenteditable. execCommand is deprecated but works in
// every browser, needs zero dependencies, and this is for reviewing AI output — not Google Docs.
import { useEffect, useRef, useState } from 'react'

const TOOLS = [
  ['bold', 'B', 'Bold'],
  ['italic', 'I', 'Italic'],
  ['formatBlock:h2', 'H2', 'Heading 2'],
  ['formatBlock:h3', 'H3', 'Heading 3'],
  ['formatBlock:p', '¶', 'Paragraph'],
  ['insertUnorderedList', '•', 'Bullet list'],
  ['createLink', '🔗', 'Insert link'],
  ['removeFormat', '✕', 'Clear formatting'],
]

export default function RichEditor({ value, onChange }) {
  const [mode, setMode] = useState('visual')
  const ref = useRef(null)

  // Push external value in only when not focused, so typing isn't clobbered.
  useEffect(() => {
    if (mode === 'visual' && ref.current && document.activeElement !== ref.current) {
      ref.current.innerHTML = value || ''
    }
  }, [value, mode])

  const exec = (cmd) => {
    ref.current?.focus()
    if (cmd === 'createLink') {
      const url = prompt('Link URL:')
      if (url) document.execCommand('createLink', false, url)
    } else if (cmd.startsWith('formatBlock:')) {
      document.execCommand('formatBlock', false, cmd.split(':')[1])
    } else {
      document.execCommand(cmd, false, null)
    }
    onChange(ref.current.innerHTML)
  }

  return (
    <div className="rounded-lg border border-edge bg-base">
      <div className="flex items-center gap-1 border-b border-edge px-2 py-1.5">
        {mode === 'visual' && TOOLS.map(([cmd, label, title]) => (
          <button key={cmd} type="button" title={title} onMouseDown={(e) => { e.preventDefault(); exec(cmd) }}
            className="rounded px-2 py-1 text-xs font-medium text-dim hover:bg-edge hover:text-ink">
            {label}
          </button>
        ))}
        <button type="button" onClick={() => setMode(mode === 'visual' ? 'html' : 'visual')}
          className="ml-auto rounded border border-edge px-2 py-1 text-xs text-dim hover:border-accent hover:text-ink">
          {mode === 'visual' ? '</> HTML' : '👁 Visual'}
        </button>
      </div>
      {mode === 'visual' ? (
        <div
          ref={ref}
          contentEditable
          suppressContentEditableWarning
          onInput={() => onChange(ref.current.innerHTML)}
          className="prose-edit h-64 overflow-y-auto px-4 py-3 text-sm outline-none"
          aria-label="Post content editor"
        />
      ) : (
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          spellCheck={false}
          className="h-64 w-full bg-transparent px-4 py-3 text-xs mono outline-none"
          aria-label="Post content HTML"
        />
      )}
    </div>
  )
}

// ── SEO checks: pure client-side scoring of what's in the editor ───────────
export function seoChecks({ title, content, excerpt, slug }) {
  const text = (content || '').replace(/<[^>]+>/g, ' ')
  const words = text.split(/\s+/).filter(Boolean).length
  const h2s = (content?.match(/<h2/gi) || []).length
  const links = (content?.match(/<a\s/gi) || []).length
  const imgs = (content?.match(/<img/gi) || []).length
  return [
    ['Title length', title?.length >= 30 && title?.length <= 60, `${title?.length || 0} chars (30–60 ideal)`],
    ['Meta description', excerpt?.length >= 120 && excerpt?.length <= 160, `${excerpt?.length || 0} chars (120–160 ideal)`],
    ['Word count', words >= 600, `${words} words (600+ recommended)`],
    ['Subheadings (H2)', h2s >= 2, `${h2s} found (2+ recommended)`],
    ['Links', links >= 1, links ? `${links} link(s)` : 'add at least one internal/external link'],
    ['Slug set', Boolean(slug), slug || 'auto-generated from title'],
    ['Image', imgs >= 1 || null, imgs ? `${imgs} inline` : 'optional, a featured image counts'],
  ]
}

export function SeoPanel({ form }) {
  const checks = seoChecks({ title: form.title, content: form.content_raw, excerpt: form.excerpt_raw, slug: form.slug })
  const passed = checks.filter(([, ok]) => ok === true).length
  const scored = checks.filter(([, ok]) => ok !== null).length
  const pct = Math.round((passed / scored) * 100)
  const tone = pct >= 80 ? 'var(--color-ok)' : pct >= 50 ? 'var(--color-accent)' : 'var(--color-bad)'
  return (
    <div className="rounded-lg border border-edge bg-base p-3">
      <div className="flex items-center gap-2 text-sm">
        <span className="font-medium">SEO</span>
        <span className="mono text-xs" style={{ color: tone }}>{pct}%</span>
        <span className="ml-1 h-1.5 flex-1 overflow-hidden rounded-full bg-edge">
          <span className="block h-full rounded-full transition-all duration-300" style={{ width: `${pct}%`, background: tone }} />
        </span>
      </div>
      <ul className="mt-2 grid gap-x-4 gap-y-1 text-xs md:grid-cols-2">
        {checks.map(([label, ok, detail]) => (
          <li key={label} className="flex items-baseline gap-1.5">
            <span style={{ color: ok === true ? 'var(--color-ok)' : ok === null ? 'var(--color-dim)' : 'var(--color-accent)' }}>
              {ok === true ? '✓' : ok === null ? '○' : '!'}
            </span>
            <span className="text-dim">{label}:</span> <span className="mono">{detail}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
