// One paragraph per page explaining what it is for and what to do first. Collapsible,
// remembered per page, so it helps a newcomer without nagging a regular.
import { useState } from 'react'

export const INTRO = {
  overview: ['Overview', 'Your control room. Post counts, running automations, the SEO health numbers and the last 28 days of Google search data for the selected site. Every tile is a link to the page that explains it.'],
  topics: ['Topics', 'The writing queue. “Find topics” asks the model for article ideas grounded in what the site already publishes; approve the good ones and the “Publish blog post” automation writes them in order, through brief → draft → QA, never publishing on its own.'],
  posts: ['Posts', 'Everything in WordPress for this site: published, scheduled, awaiting approval, drafts. Edit, approve, schedule, bulk-act. The SEO chip on each row is a quick title/meta check; the full audit lives on the SEO page.'],
  automations: ['Automations', 'Every scheduled job the system runs: blog writer, site crawl, Google sync, Core Web Vitals. Run now, dry-run, pause, edit the schedule in plain English, or open a job to see its code and history. Jobs without a pinned site run against the site selected top-right.'],
  schedule: ['Schedule', 'When each automation fires next, plus scheduled WordPress posts. Times are UTC.'],
  logs: ['Logs', 'Every run with its live output. A failed run can be retried from here; a running one can be stopped.'],
  performance: ['Performance', 'Real numbers from Google Search Console and GA4: clicks, impressions, positions, organic sessions. Below the tiles are the rules that turn data into work: page-1 pushes, weak-CTR rewrites, cannibalization, queries you already appear for, declines, and the refresh plan (Refresh / Expand / Re-optimize / Merge / Redirect).'],
  keywords: ['Keywords', 'Keyword research without a paid tool. Research starts from the business profile; harvest pulls what the site already targets; clustering groups keywords into one-page topics; mapping decides which existing URL should rank or whether a new page is justified. “Analyse SERPs” checks real Google results to validate intent, see what format ranks, and find who outranks you. Everything the model produces is a suggestion until you approve it.'],
  content: ['Content', 'The writing pipeline and the safety net. Business profile: what the company sells, to whom, and the only facts the writer may state. Briefs: brief → draft → QA → approve (creates a WordPress draft, never publishes). Change queue: every edit the system wants to make to WordPress, with before/after and one-click rollback.'],
  seo: ['SEO', 'Technical: crawl the site and get an explainable score with every issue listed by rule and page - status codes, canonicals, sitemap, duplicates, headings, titles, meta, links, images, schema, security, Core Web Vitals. Click a page for AI title/meta/H1 suggestions you approve. Content: the WordPress-side audit of each post and page.'],
  theme: ['Theme', 'The active theme’s files. PHP saves are syntax-checked first and every save keeps a backup. Use it for header tags, tracking snippets and template-level fixes the SEO audit points at.'],
  sites: ['Sites', 'WordPress sites this dashboard manages, plus the Google connection. One Google login covers every site; each site names its own Search Console property and GA4 property id.'],
  health: ['Health', 'Is everything up: WordPress API, scheduler, workers, database, how old each dataset is, and what the AI calls cost.'],
  secrets: ['Secrets & users', 'API keys live in .env and are only ever shown masked. Below: dashboard users and roles - admin (everything), seo (approve, publish, roll back), content (write), viewer (read).'],
  guide: ['Guide', 'The manual: what every page does, how to use it, what to do next, and how to fix the common problems.'],
  audit: ['Audit', 'Who did what, when, with before/after values. Every automated and manual change lands here.'],
}

export default function PageIntro({ page }) {
  const entry = INTRO[page]
  const key = `intro_hidden_${page}`
  const [hidden, setHidden] = useState(() => localStorage.getItem(key) === '1')
  if (!entry) return null
  const [title, text] = entry
  return (
    <div className="mb-5 flex items-start gap-3">
      <div className="min-w-0">
        <h1 className="text-lg font-bold">{title}</h1>
        {!hidden && <p className="mt-1 max-w-4xl text-sm text-dim">{text}</p>}
      </div>
      <button className="ml-auto shrink-0 rounded border border-edge px-2 py-0.5 text-xs text-dim hover:border-accent" aria-label={hidden ? 'Show page help' : 'Hide page help'}
        onClick={() => { localStorage.setItem(key, hidden ? '0' : '1'); setHidden(!hidden) }}>{hidden ? '? help' : 'hide'}</button>
    </div>
  )
}
