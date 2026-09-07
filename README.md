# WordPress Content Automation

A self-hosted dashboard that plans, writes, and publishes blog content for one or more WordPress sites.

## What it does

- **Topic engine**: researches your site and suggests blog topics with a relevance score and a reason. You approve the ones you want and they join a writing queue.
- **Writer**: for each queued topic it picks target keywords from what currently ranks, researches recent facts, writes the article in a natural voice, then runs a second editing pass. Articles include internal links to your existing pages.
- **Images**: finds a matching stock photo on Pexels for every post (AI illustration as fallback), uploads it to the media library, and sets it as the featured image.
- **SEO**: a site-wide audit page scores every post and page, suggests fixes (like missing meta descriptions), and applies them when you click Approve. A small must-use plugin outputs meta tags, Open Graph, canonical URLs and Article structured data.
- **Publishing control**: per-job policy for always-draft, auto-publish above an SEO score threshold, or publish immediately. Scheduled runs via cron presets.
- **Dashboard**: posts CRUD, run history with live logs, schedule view, health checks, notifications, multi-site switching, and login.

## Stack

- Backend: FastAPI + SQLite + APScheduler (Python, stdlib-first)
- Frontend: React + Vite + Tailwind
- Content: Groq API (article generation and research), Pexels API (images)
- Publishing: WordPress REST API with Application Passwords

## Setup

1. `python3 -m venv .venv && .venv/bin/pip install django django-ninja pyyaml apscheduler`
2. `cd dashboard && npm install && npm run build`
3. Create `.env` in the repo root:

```
WEBSITE_LINK=https://yoursite.com
WP_USER=your-wp-username
APPLICATION_PASSWORD=xxxx xxxx xxxx xxxx
GROQ_KEY=gsk_...
PEXELS_KEY=...        # optional, enables stock photos
```

4. `.venv/bin/python manage.py migrate && .venv/bin/python manage.py runserver 127.0.0.1:7071`
5. Open http://localhost:7071 and create your login.

Upload `servelens-seo.php` to `wp-content/mu-plugins/` on each WordPress site for the SEO tag output.

## Notes

- Credentials never reach the browser; the sites file and .env stay out of git.
- Each connected site gets its own posts, SEO audit, pipeline and health view.
- The default publish policy is draft, so nothing goes live without a human click.

## Google Search Console + GA4

1. Google Cloud → new project → enable **Search Console API**, **Analytics Data API** (and optionally **Analytics Admin API**).
2. Google Auth Platform → Audience → add yourself as a test user.
3. Clients → create **Web application** client with redirect URI `http://127.0.0.1:7071/api/google/callback`.
4. Dashboard → Secrets → `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`.
5. Dashboard → Sites → **Connect Google** → sign in → **List my properties** → fill GSC property (`sc-domain:example.com`) and GA4 numeric property id per site → Save.
6. Performance → **Sync now** (the `sync-google` automation also runs nightly).

Optional keys: `BRAVE_KEY` (SERP analysis), `PAGESPEED_KEY` (Core Web Vitals).

## Roles

Django groups `admin` / `seo` / `content` / `viewer`. The first account is admin. Approve, publish, rollback need `seo` or `admin`; delete and settings need `admin`. Manage users on the Secrets page.
