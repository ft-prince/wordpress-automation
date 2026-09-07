// The manual. What each page does, how to use it, and what to do next. Written for
// someone who opens PressPilot for the first time with a WordPress site and a Groq key.
import { useState } from 'react'

const SECTIONS = [
  {
    id: 'what', title: 'What PressPilot is',
    body: [
      'PressPilot is a control plane for one or more WordPress sites. It crawls the site, audits technical and on-page SEO, researches keywords, decides which page should rank for what, writes content from a brief, QA-checks it, and puts every change through an approval gate with rollback. Scheduled automations keep it running; Google Search Console and GA4 feed real performance data back in.',
      'Two rules drive everything: the model suggests, a human approves; and nothing is ever auto-published. Drafts land in WordPress as drafts. Publishing is always a click on the Posts page.',
    ],
  },
  {
    id: 'start', title: 'First hour: the order that works',
    steps: [
      ['Sites', 'Connect the WordPress site (application password). Optional but recommended: Connect Google and set the Search Console property and GA4 property id.'],
      ['Secrets', 'Check GROQ_KEY is present. Add GOOGLE_API_KEY (PageSpeed Insights) if you want Core Web Vitals.'],
      ['SEO → Crawl site', 'One click. About a minute per 100 pages. Everything downstream reads this crawl.'],
      ['Content → Business profile → Draft from crawl', 'Review what the model inferred, correct it, add approved facts and priorities, Save. This is the context every prompt uses.'],
      ['Keywords → Research → Cluster → Map', 'Three clicks. Then open a few clusters, fix anything the model got wrong, approve the mappings you agree with.'],
      ['Keywords → Analyse SERPs', 'Checks real Google results for your top clusters: true intent, ranking format, who outranks you, what they cover that you do not.'],
      ['Topics → Find topics → approve', 'The writing queue. The nightly “Publish blog post” automation writes the next approved topic through brief → draft → QA.'],
      ['Performance', 'Once Google is connected, run Sync. The refresh plan tells you which existing pages to fix first.'],
    ],
  },
  {
    id: 'overview', title: 'Overview',
    what: 'The control room for the selected site.',
    how: 'Alerts at the top (connection, failed runs, stale data, changes waiting for approval). Post counts and automation health. SEO tiles: technical score (from the last crawl), QA pass rate (briefs), pending changes, clicks in 28 days. Then the content pipeline, upcoming posts, recent runs, the 7-day outcome heatmap and the search-performance graph.',
    next: 'Every tile is a link. A red or amber tile is the place to go next.',
  },
  {
    id: 'topics', title: 'Topics',
    what: 'The article queue.',
    how: '“Find topics” asks the model for ideas grounded in what the site already publishes (site gaps, what ranks in the niche, what is trending). Each suggestion carries a relevance score and a one-line reason. Approve the good ones, reject the rest, reorder the queue with the arrows, or add your own title. Everything is per site.',
    next: 'Keep two or more topics approved. The “Publish blog post” automation claims the top one each run; if QA fails it leaves the brief for you on the Content page and moves on.',
  },
  {
    id: 'posts', title: 'Posts',
    what: 'Everything in WordPress: published, scheduled, awaiting approval, drafts, trash.',
    how: 'Edit in the built-in editor (title, content, excerpt/meta, slug, category, featured image). Approve, schedule, publish, trash, restore. Bulk actions on selected rows. The SEO chip is a quick title/meta length check. “Generate” writes a one-off article without touching the topic queue.',
    next: 'Drafts created by the pipeline show up here as drafts; review and publish from this page. Publishing needs the seo or admin role.',
  },
  {
    id: 'automations', title: 'Automations, Schedule, Logs',
    what: 'The jobs and their history.',
    how: 'Automations lists every job: Publish blog post (Mon/Thu 09:00 UTC), Crawl site (Mon 03:00), Sync Search Console + GA4 (daily 04:30), Core Web Vitals (Tue 05:00). Run now, Dry run, Pause, Duplicate, Delete. Open a job for its YAML, schedule in plain English, source code (syntax-checked on save, backed up), run history and durations. Jobs without a pinned site run against the site selected top-right. Schedule shows what fires next. Logs streams every run live; failed runs can be retried, running ones stopped.',
    next: 'If the Health page says the scheduler is down, nothing scheduled will fire: restart the server.',
  },
  {
    id: 'performance', title: 'Performance',
    what: 'Real search and traffic data, and the rules that turn it into work.',
    how: 'Tiles compare the last 28 days with the 28 before. Then: Refresh plan (one action per page: Refresh, Expand, Re-optimize, Merge, Redirect), Page-1 opportunities (positions 8-20 with impressions), CTR opportunities (page-1 rankings getting under half the clicks they should: rewrite title/meta), Cannibalization (one query, several of your pages), New keyword opportunities (queries you already appear for that Keywords does not track; one click adds them), Ranking and Traffic decline, Top landing pages.',
    next: 'Needs Google connected on Sites and at least one sync. Search Console data is final about three days late; that is expected.',
  },
  {
    id: 'keywords', title: 'Keywords',
    what: 'Keyword research, clustering and URL mapping without a paid tool.',
    how: 'Research from profile: seed, long-tail and question keywords from the business profile, plus what the crawl, topics and briefs already carry; each scored for intent, business relevance and commercial value. Cluster: groups keywords into one-page topics with a parent topic and a primary keyword; intents are never mixed. Map: for each cluster, an existing page, a page to improve, a new page, or ignore, existing pages preferred. Open a cluster to change intent, role, action, target URL; merge, split, move keywords, set the primary, approve the mapping. Analyse SERPs: real Google results for the primary keyword; validated intent, ranking format, patterns in the winning titles, gaps versus your target page, and your own rank. Tabs: Unclustered, Cannibalization, Content gaps & pillars (missing commercial pages, pages to improve, supporting content, pillar map), SEO competitors (domains that keep outranking you).',
    next: 'Approve mappings you agree with; “new” clusters with commercial intent are your next landing pages; supporting-content clusters become topics.',
  },
  {
    id: 'content', title: 'Content',
    what: 'The writing pipeline and the safety net.',
    how: 'Business profile: what the company sells, to whom, where, the brand voice, business priorities with weights, and the approved facts, the only claims the writer may state as fact. “Draft from crawl” fills it once; you edit and save. Briefs & drafts: type a topic → brief (keyword, intent, audience, outline, FAQs, internal links from real pages, CTA) → edit if needed → Write draft → Run QA → Suggest links (inserted into the draft with one click) → Generate schema (Article + FAQ JSON-LD, injected on approve) → Approve, which creates a WordPress draft. QA runs twelve deterministic checks, a duplicate-phrase check against the crawl, and a model review for intent, coverage, unsupported claims, stuffing and readability; the score is the sum of what passed. Change queue: every edit to WordPress the system proposed or applied, with before/after; Apply, Reject, Roll back.',
    next: 'A brief left in “qa” is waiting for you; fix the draft or re-draft, then approve. Roll back any applied change from the queue if it made things worse.',
  },
  {
    id: 'seo', title: 'SEO',
    what: 'The technical audit and the WordPress content audit.',
    how: 'Technical (crawl): Crawl site fetches the sitemap and follows internal links, records status codes, redirect chains, canonicals, robots, titles, meta, headings, word counts, links, images, JSON-LD and security headers. Core Web Vitals runs PageSpeed Insights on the top 30 pages. The score is explainable: every issue is listed by rule with severity and the pages affected. Click a page: its metrics, its issues, and AI suggestions for title, meta and H1 that you approve one by one (written through the change gate, so they roll back). Content (WordPress): each post and page checked for meta, title, thin content, headings, links, featured image, slug; fixable issues get an AI-written fix you approve.',
    next: 'Re-crawl after big changes and weekly by schedule. High-severity rules first: broken pages, orphans, duplicates, missing H1, poor LCP.',
  },
  {
    id: 'theme', title: 'Theme',
    what: 'The active theme’s files, editable.',
    how: 'PHP is syntax-checked before saving and every save or delete keeps a backup on the server. Needs the servelens-seo.php helper plugin in wp-content/mu-plugins.',
    next: 'Use it for template-level fixes the audit points at: missing H1 in a template, header tags, tracking snippets.',
  },
  {
    id: 'sites', title: 'Sites',
    what: 'WordPress sites and the Google connection.',
    how: 'Connect a site with its URL, user and application password (tested before saving). Switch the active site top-right; every page is scoped to it. Google: one login covers all sites (Connect Google, then List my properties); each site gets its own Search Console property (sc-domain:example.com) and GA4 numeric property id, plus country/language.',
    next: 'If Search Console returns “insufficient permission”, your Google account needs Full permission on that property.',
  },
  {
    id: 'health', title: 'Health, Secrets, Audit',
    what: 'Is everything up, what it costs, who did what.',
    how: 'Health: WordPress API latency, scheduler, workers, database, data freshness (crawl, Search Console, GA4 age), AI spend (today, 7 days, 30 days). Secrets: keys in .env, shown masked, rotate in place; below it, users and roles. Audit: every automated and manual change with before/after values.',
    next: 'Stale-data warnings mean a scheduled job is not running; check Automations.',
  },
  {
    id: 'roles', title: 'Roles',
    body: [
      'admin: everything, including users, secrets, sites, delete. seo: approve changes and briefs, publish, roll back. content: write briefs, drafts, topics, edit posts. viewer: read only. The first account is admin; manage others on the Secrets page.',
    ],
  },
  {
    id: 'faq', title: 'Troubleshooting',
    steps: [
      ['“model returned no content” or a Groq 429', 'The free Groq tier allows 200k tokens a day on the main model. Calls fall back to the smaller model automatically; wait for the daily reset for full quality.'],
      ['Overview graph empty', 'Google is not connected for this site, or no sync has run yet. Sites → Connect Google → set properties → Performance → Sync now.'],
      ['Scheduler down', 'Restart the server: python manage.py runserver 127.0.0.1:7071.'],
      ['Meta description fix “ignored by WordPress”', 'Upload servelens-seo.php v1.1+ to wp-content/mu-plugins on that site.'],
      ['H1 suggestion cannot be applied', 'The H1 comes from the theme template, not the post; edit it under Theme.'],
      ['A change made things worse', 'Content → Change queue → Roll back on that change.'],
    ],
  },
]

export default function Guide() {
  const [open, setOpen] = useState(SECTIONS[0].id)
  return (
    <div className="grid gap-6 md:grid-cols-[200px_1fr]">
      <nav className="sticky top-6 self-start text-sm" aria-label="Guide sections">
        {SECTIONS.map((s) => (
          <a key={s.id} href={`#guide-${s.id}`} onClick={() => setOpen(s.id)}
            className={`block rounded px-2 py-1 ${open === s.id ? 'bg-panel text-ink' : 'text-dim hover:text-ink'}`}>{s.title}</a>
        ))}
      </nav>
      <div className="max-w-3xl space-y-8">
        {SECTIONS.map((s) => (
          <section key={s.id} id={`guide-${s.id}`} className="rounded-xl border border-edge bg-panel p-5">
            <h2 className="mb-3 text-base font-bold text-ink">{s.title}</h2>
            {s.body?.map((p, i) => <p key={i} className="mb-2 text-sm text-dim">{p}</p>)}
            {s.what && (
              <dl className="space-y-3 text-sm">
                <div><dt className="text-xs uppercase tracking-widest text-dim">What</dt><dd>{s.what}</dd></div>
                <div><dt className="text-xs uppercase tracking-widest text-dim">How</dt><dd className="text-dim">{s.how}</dd></div>
                <div><dt className="text-xs uppercase tracking-widest text-dim">What next</dt><dd style={{ color: 'var(--color-accent)' }}>{s.next}</dd></div>
              </dl>
            )}
            {s.steps && (
              <ol className="list-decimal space-y-2 pl-5 text-sm">
                {s.steps.map(([label, text], i) => <li key={i}><span className="font-medium">{label}</span> <span className="text-dim">{text}</span></li>)}
              </ol>
            )}
          </section>
        ))}
      </div>
    </div>
  )
}
