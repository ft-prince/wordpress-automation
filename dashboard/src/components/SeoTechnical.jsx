// Technical SEO: crawl-backed site audit. Issues grouped by rule, per-page drawer with
// AI title / meta / H1 suggestions that the user approves before anything is written.
import { useEffect, useState } from 'react'
import { api } from '../api'
import { btnGhost, btnPrimary, Empty, Modal, Spinner } from './bits'

const SEV = {
  high: 'var(--color-bad)',
  medium: 'var(--color-accent)',
  low: 'var(--color-dim)',
}
const scoreTone = (s) => (s == null ? 'var(--color-dim)' : s >= 80 ? 'var(--color-ok)' : s >= 50 ? 'var(--color-accent)' : 'var(--color-bad)')
const short = (u) => u.replace(/^https?:\/\/[^/]+/, '') || '/'

function Sev({ level }) {
  return (
    <span className="rounded-full px-2 py-0.5 text-[10px] uppercase mono"
      style={{ color: SEV[level], border: `1px solid color-mix(in srgb, ${SEV[level]} 40%, transparent)` }}>
      {level}
    </span>
  )
}

function IssueGroup({ group, onPage }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="rounded-lg border border-edge bg-panel">
      <button onClick={() => setOpen(!open)} className="flex w-full items-center gap-3 px-4 py-2.5 text-left text-sm">
        <Sev level={group.severity} />
        <span className="font-medium">{group.label}</span>
        <span className="text-xs text-dim">{group.detail}</span>
        <span className="ml-auto mono text-xs text-dim">{group.count} page{group.count === 1 ? '' : 's'}</span>
      </button>
      {open && (
        <ul className="border-t border-edge px-4 py-2 text-xs mono">
          {group.pages.map((p, i) => (
            <li key={i} className="flex flex-wrap items-center gap-2 py-1">
              <button className="truncate text-left underline-offset-2 hover:underline" onClick={() => onPage(p.url)} title={p.url}>
                {short(p.url)}
              </button>
              {Object.entries(p).filter(([k]) => !['url', 'targets', 'variants'].includes(k)).map(([k, v]) => (
                <span key={k} className="text-dim">{k}={String(v)}</span>
              ))}
              {(p.targets || p.variants) && (
                <span className="w-full pl-4 text-dim">{(p.targets || p.variants).slice(0, 5).map((t) => short(t)).join('  ·  ')}</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

const FIELDS = [
  ['title', 'Title tag', 'title'],
  ['meta_description', 'Meta description', 'meta_description'],
  ['h1', 'H1', 'h1'],
]

function PageDrawer({ pageId, notify, onClose, onChanged }) {
  const [page, setPage] = useState(null)
  const [sug, setSug] = useState(null)
  const [busy, setBusy] = useState('')
  useEffect(() => { api.seoPage(pageId).then(setPage).catch((e) => { notify(e.message, true); onClose() }) }, [pageId])
  if (!page) return <Modal title="Page" onClose={onClose} wide><Spinner /></Modal>

  const suggest = () => {
    setBusy('suggest')
    api.suggestOnpage(pageId).then(setSug).catch((e) => notify(e.message, true)).finally(() => setBusy(''))
  }
  const apply = (field, value) => {
    setBusy(field)
    api.applyOnpage(pageId, field, value)
      .then(() => { notify(`Applied ${field}`); setPage({ ...page, [field === 'h1' ? 'h1' : field]: field === 'h1' ? [value] : value }); onChanged?.() })
      .catch((e) => notify(e.message, true))
      .finally(() => setBusy(''))
  }
  const current = { title: page.title, meta_description: page.meta_description, h1: page.h1.join(' | ') }

  return (
    <Modal title={short(page.url)} onClose={onClose} wide>
      <div className="space-y-4 text-sm">
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-lg font-bold mono" style={{ color: scoreTone(page.score) }}>{page.score ?? '—'}%</span>
          <a href={page.url} target="_blank" rel="noreferrer" className="text-dim underline-offset-2 hover:underline">open page</a>
          <span className="mono text-xs text-dim">HTTP {page.status} · {page.word_count} words · {page.h2_count} H2 · {page.internal_links} links in body · depth {page.depth}</span>
          {page.psi?.score != null && <span className="mono text-xs" style={{ color: scoreTone(page.psi.score) }}>PSI {page.psi.score} · LCP {(page.psi.lcp_ms / 1000).toFixed(1)}s · CLS {page.psi.cls} · TBT {page.psi.tbt_ms}ms{page.psi.inp_ms ? ` · INP ${page.psi.inp_ms}ms` : ''}</span>}
          {page.wp_base ? <span className="mono text-xs" style={{ color: 'var(--color-ok)' }}>WP {page.wp_base}#{page.wp_id}</span>
            : <span className="mono text-xs text-dim">not a WordPress item (theme/template)</span>}
        </div>

        <div className="space-y-2">
          {FIELDS.map(([key, label]) => (
            <div key={key} className="rounded-lg border border-edge bg-base p-3">
              <div className="text-xs uppercase tracking-widest text-dim">{label}</div>
              <div className="mt-1 mono text-xs">{current[key] || <span className="text-dim">(missing)</span>}
                {current[key] && <span className="ml-2 text-dim">{current[key].length} chars</span>}</div>
              {sug && sug[key] && sug[key] !== current[key] && (
                <div className="mt-2 flex items-start gap-3 rounded bg-edge/40 p-2">
                  <div className="min-w-0 flex-1 mono text-xs" style={{ color: 'var(--color-ok)' }}>{sug[key]} <span className="text-dim">{sug[key].length} chars</span></div>
                  <button className={btnPrimary} disabled={!sug.can_apply || busy === key || (key === 'h1' && page.wp_base !== 'posts')}
                    title={key === 'h1' && page.wp_base !== 'posts' ? 'H1 on this page comes from the theme template' : ''}
                    onClick={() => apply(key, sug[key])}>{busy === key ? 'Applying…' : 'Approve'}</button>
                </div>
              )}
            </div>
          ))}
          <div className="flex items-center gap-3">
            <button className={btnGhost} disabled={busy === 'suggest'} onClick={suggest}>{busy === 'suggest' ? 'Thinking…' : sug ? 'Suggest again' : 'Suggest title / meta / H1'}</button>
            {sug && <span className="text-xs text-dim">target keyword: <span className="mono text-ink">{sug.primary_keyword}</span> — {sug.reason}</span>}
          </div>
        </div>

        <div>
          <div className="mb-1 text-xs uppercase tracking-widest text-dim">Issues on this page</div>
          {page.issues.length === 0 ? <p style={{ color: 'var(--color-ok)' }}>✓ no issues</p> : (
            <ul className="space-y-1">
              {page.issues.map((i, n) => (
                <li key={n} className="flex items-center gap-2 text-xs"><Sev level={i.severity} /><span>{i.label}</span><span className="text-dim">{i.detail}</span></li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </Modal>
  )
}

export default function SeoTechnical({ notify }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [openPage, setOpenPage] = useState(null)
  const [filter, setFilter] = useState('')
  const [issueQ, setIssueQ] = useState('')
  const [sev, setSev] = useState('')

  const load = () => api.technicalSeo().then((d) => { setData(d); setError(null) }).catch((e) => setError(e.message))
  useEffect(() => { load() }, [])
  const running = data?.run?.status === 'running'
  useEffect(() => {
    if (!running) return
    const t = setInterval(load, 3000)
    return () => clearInterval(t)
  }, [running])

  const start = () => api.startCrawl().then(() => { notify('crawl started'); load() }).catch((e) => notify(e.message, true))

  if (error) return <p className="text-sm" style={{ color: 'var(--color-bad)' }}>{error}</p>
  if (!data) return <Spinner label="loading crawl…" />

  const { crawl, summary, issues, pages, run } = data
  const byUrl = (url) => pages.find((p) => p.url === url)

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-4 md:flex-row md:items-center">
        <div className="grid flex-1 grid-cols-2 gap-3 md:grid-cols-5">
          {[['site score', data.score == null ? '—' : `${data.score}%`, scoreTone(data.score)],
            ['pages crawled', summary?.pages ?? '—'],
            ['high', summary?.high ?? '—', summary?.high ? SEV.high : undefined],
            ['medium', summary?.medium ?? '—', summary?.medium ? SEV.medium : undefined],
            ['low', summary?.low ?? '—'],
          ].map(([label, value, tone]) => (
            <div key={label} className="rounded-xl border border-edge bg-panel px-4 py-3">
              <div className="text-2xl font-bold mono" style={tone ? { color: tone } : undefined}>{value}</div>
              <div className="mt-0.5 text-xs uppercase tracking-widest text-dim">{label}</div>
            </div>
          ))}
        </div>
        <div className="text-right">
          <button className={btnPrimary} disabled={running} onClick={start}>{running ? 'Crawling…' : crawl ? 'Re-crawl' : 'Crawl site'}</button>
          {crawl?.status === 'done' && <button className={`${btnGhost} ml-2`} disabled={data.psi_run?.status === 'running'} title="PageSpeed Insights on the top 30 pages (mobile)"
            onClick={() => api.startPagespeed().then(() => { notify('Core Web Vitals check started - see Logs'); load() }).catch((e) => notify(e.message, true))}>{data.psi_run?.status === 'running' ? 'Measuring…' : 'Core Web Vitals'}</button>}
          {crawl?.finished_at && <p className="mt-1 text-xs text-dim mono">crawled {new Date(crawl.finished_at).toLocaleString()}</p>}
          {running && <p className="mt-1 text-xs text-dim mono">running · see Logs for progress</p>}
        </div>
      </div>

      {!crawl && !running && (
        <div className="max-w-xl rounded-xl border border-edge bg-panel p-8 text-center">
          <p className="text-sm text-dim">No crawl yet for this site. The crawler reads the sitemap, follows internal links and checks status codes, canonicals, titles, meta, headings, links, images, schema and security headers.</p>
          <button className={`${btnPrimary} mt-4`} onClick={start}>Crawl site now</button>
          <p className="mt-2 text-xs text-dim">Runs as the “Crawl site for SEO” automation (weekly by default). A 100-page site takes about a minute.</p>
        </div>
      )}

      {crawl?.status === 'failed' && <p className="text-sm" style={{ color: 'var(--color-bad)' }}>last crawl failed: {crawl.note}</p>}

      {issues?.length > 0 && (
        <section className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-xs uppercase tracking-widest text-dim">Issues by rule ({summary.issues} across {summary.affected_pages} pages)</h3>
            <span className="ml-auto flex gap-1">{['', 'high', 'medium', 'low'].map((s) => <button key={s} onClick={() => setSev(s)} className={`rounded-full border px-2 py-0.5 text-[10px] uppercase mono ${sev === s ? 'border-accent text-ink' : 'border-edge text-dim'}`}>{s || 'all'}</button>)}</span>
            <input className="w-56 rounded-lg border border-edge bg-base px-3 py-1.5 text-xs outline-none focus:border-accent" placeholder="filter by rule or URL" value={issueQ} onChange={(e) => setIssueQ(e.target.value)} />
          </div>
          {issues.filter((g) => (!sev || g.severity === sev) && (!issueQ || g.label.toLowerCase().includes(issueQ.toLowerCase()) || g.code.includes(issueQ.toLowerCase()) || g.pages.some((p) => p.url.includes(issueQ))))
            .map((g) => <IssueGroup key={g.code} group={issueQ && !g.label.toLowerCase().includes(issueQ.toLowerCase()) && !g.code.includes(issueQ.toLowerCase()) ? { ...g, pages: g.pages.filter((p) => p.url.includes(issueQ)) } : g} onPage={(url) => { const p = byUrl(url); if (p) setOpenPage(p.id) }} />)}
        </section>
      )}
      {crawl?.status === 'done' && issues?.length === 0 && <Empty quip="Clean crawl. Nothing to fix." />}

      {pages?.length > 0 && (
        <section>
          <div className="mb-2 flex items-center gap-3">
            <h3 className="text-xs uppercase tracking-widest text-dim">Pages ({pages.length})</h3>
            <input className="ml-auto w-64 rounded-lg border border-edge bg-base px-3 py-1.5 text-xs outline-none focus:border-accent"
              placeholder="filter by URL or title" value={filter} onChange={(e) => setFilter(e.target.value)} />
          </div>
          <div className="overflow-hidden rounded-xl border border-edge">
            <table className="w-full text-xs">
              <thead className="bg-panel text-left uppercase tracking-widest text-dim">
                <tr><th className="px-3 py-2">score</th><th className="px-3 py-2">url</th><th className="px-3 py-2">title</th><th className="px-3 py-2">http</th><th className="px-3 py-2">words</th><th className="px-3 py-2">psi</th><th className="px-3 py-2">lcp</th><th className="px-3 py-2">issues</th></tr>
              </thead>
              <tbody>
                {pages.filter((p) => !filter || p.url.includes(filter) || (p.title || '').toLowerCase().includes(filter.toLowerCase())).slice(0, 300).map((p) => (
                  <tr key={p.id} className="cursor-pointer border-t border-edge hover:bg-edge/30" onClick={() => setOpenPage(p.id)}>
                    <td className="px-3 py-1.5 mono font-bold" style={{ color: scoreTone(p.score) }}>{p.score ?? '—'}</td>
                    <td className="max-w-xs truncate px-3 py-1.5 mono" title={p.url}>{short(p.url)}</td>
                    <td className="max-w-xs truncate px-3 py-1.5" title={p.title}>{p.title || <span className="text-dim">(no title)</span>}</td>
                    <td className="px-3 py-1.5 mono" style={p.status && p.status >= 400 ? { color: SEV.high } : undefined}>{p.status ?? 'ERR'}</td>
                    <td className="px-3 py-1.5 mono">{p.words}</td>
                    <td className="px-3 py-1.5 mono" style={p.psi != null ? { color: scoreTone(p.psi) } : undefined}>{p.psi ?? '—'}</td>
                    <td className="px-3 py-1.5 mono" style={p.lcp_ms > 4000 ? { color: SEV.high } : p.lcp_ms > 2500 ? { color: SEV.medium } : undefined}>{p.lcp_ms != null ? `${(p.lcp_ms / 1000).toFixed(1)}s` : '—'}</td>
                    <td className="px-3 py-1.5 mono">{p.issues}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {openPage && <PageDrawer pageId={openPage} notify={notify} onClose={() => setOpenPage(null)} onChanged={load} />}
    </div>
  )
}
