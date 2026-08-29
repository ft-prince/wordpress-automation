// Compact SEO indicator for post rows. Full checks live in the editor's SeoPanel.
export default function SeoChip({ seo }) {
  if (!seo) return null
  const issues = []
  if (!seo.meta_ok) issues.push(seo.meta_len === 0 ? 'no meta description' : `meta ${seo.meta_len} chars (100–170)`)
  if (!seo.title_ok) issues.push('title length off (25–65)')
  const ok = issues.length === 0
  const color = ok ? 'var(--color-ok)' : 'var(--color-accent)'
  return (
    <span
      title={ok ? 'Title and meta description look good' : `Fix: ${issues.join(' · ')}`}
      className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] mono"
      style={{ color, border: `1px solid color-mix(in srgb, ${color} 40%, transparent)` }}
    >
      SEO {ok ? '✓' : '!'}
    </span>
  )
}
