"""Write the next approved topic and post it. This is the cron entrypoint.
Topics come from the dashboard queue (SQLite); topics.txt only feeds the one-time migration."""
import os
import sys
from datetime import datetime, timezone

import gen
import wp

HERE = os.path.dirname(os.path.abspath(__file__))
TOPICS = os.path.join(HERE, "topics.txt")   # legacy — read by core.topics migration only
DONE = os.path.join(HERE, "posted.txt")


def _read(path):
    """Non-empty, non-comment lines. Kept for the migration path."""
    if not os.path.exists(path):
        return []
    with open(path) as fh:
        return [ln.strip() for ln in fh if ln.strip() and not ln.startswith("#")]


def _site_pages(env):
    """Published content the writer may internally link to."""
    pages = []
    try:
        for p in wp.call("/posts?status=publish&per_page=10&_fields=title,link", env=env):
            pages.append({"title": p["title"]["rendered"], "url": p["link"]})
        for base in ("pages", "solution"):
            try:
                for p in wp.call(f"/{base}?per_page=15&_fields=title,link", env=env):
                    pages.append({"title": p["title"]["rendered"], "url": p["link"]})
            except RuntimeError:
                pass
    except RuntimeError:
        pass
    return pages


SEO_PUBLISH_THRESHOLD = 80


def seo_score(title, meta, html, has_image):
    """Same checks the dashboard SEO panel runs — the auto-publish gate."""
    import re

    text = re.sub(r"<[^>]+>", " ", html)
    checks = [
        30 <= len(title) <= 60,
        120 <= len(meta) <= 160,
        len(text.split()) >= 600,
        len(re.findall(r"<h2", html, re.I)) >= 2,
        len(re.findall(r"<a\s", html, re.I)) >= 1,
        has_image,
    ]
    return round(sum(checks) / len(checks) * 100)


def run(status="draft", dry_run=False, site=None, policy=None, category=None):
    """policy overrides status: 'draft' | 'publish' | 'seo80' (publish only if score >= 80)."""
    from core import images, topics

    env = None
    if site:
        from core import sites as site_registry

        env = {**wp.load_env(), **site_registry.env_for(site)}
        print(f"site: {site} ({env['WEBSITE_LINK']})")

    topic = topics.next_approved(site)
    if not topic:
        print(f"topic queue is empty. Approve topics on the dashboard "
              f"({topics.queue_depth(site)} queued)")
        return 0

    print(f"topic #{topic['id']}: {topic['title']}  (source: {topic['source']})")
    link_env = env or wp.load_env()
    title, meta, html, keywords = gen.write_full(topic["title"], env=env,
                                                site_pages=_site_pages(link_env))
    print(f"title: {title} ({len(html)} chars)")
    print(f"keywords: primary='{keywords['primary']}' secondary={keywords['secondary']}")
    if meta:
        print(f"meta:  {meta}")

    if policy == "publish":
        status = "publish"
    elif policy == "seo80":
        status = "draft"   # gate decides after the image lands

    # Every automated post gets a real category — never Uncategorized.
    categories = []
    try:
        from core import wp_api

        categories = [wp_api.ensure_category(category or "Insights", site=site)]
    except RuntimeError as exc:
        print(f"category skipped: {exc}")

    post = wp.publish(title, html, status=status, dry_run=dry_run, excerpt=meta,
                      categories=categories, env=env)
    if dry_run:
        print("dry run — nothing sent to WordPress")
        return 0

    topics.mark_written(topic["id"], post_id=post["id"])
    print(f"{post['status']} #{post['id']} -> {post['link']}")

    # Featured image is an enhancer — a failure must never fail the post.
    has_image = False
    try:
        media_id = images.set_featured(post["id"], keywords["primary"] or title, site=site)
        has_image = True
        print(f"featured image set (media #{media_id})")
    except RuntimeError as exc:
        print(f"featured image skipped: {exc}")

    if policy == "seo80":
        score = seo_score(title, meta, html, has_image)
        if score >= SEO_PUBLISH_THRESHOLD:
            from core import wp_api

            wp_api.update_post(post["id"], {"status": "publish"}, site=site)
            print(f"SEO score {score}% >= {SEO_PUBLISH_THRESHOLD}% — auto-published")
        else:
            print(f"SEO score {score}% < {SEO_PUBLISH_THRESHOLD}% — left as draft for review")
    return 0


if __name__ == "__main__":
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        site_arg = sys.argv[sys.argv.index("--site") + 1] if "--site" in sys.argv else None
        policy_arg = sys.argv[sys.argv.index("--policy") + 1] if "--policy" in sys.argv else None
        cat_arg = sys.argv[sys.argv.index("--category") + 1] if "--category" in sys.argv else None
        code = run(
            status="publish" if "--publish" in sys.argv else "draft",
            dry_run="--dry-run" in sys.argv,
            site=site_arg,
            policy=policy_arg,
            category=cat_arg,
        )
    except Exception as exc:
        print(f"[{stamp}] FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
    print(f"[{stamp}] done")
    raise SystemExit(code)
