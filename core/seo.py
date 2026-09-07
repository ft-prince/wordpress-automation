"""SEO layer: the WP-content audit (per item, saved in SeoAudit), the crawl-based
technical audit (technical.py over Page rows), and AI on-page suggestions
(title / meta / H1) that a human approves before anything is written to WordPress."""
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from django.utils import timezone

import wp
from core import crawl as crawler
from core import changes, sites, store, technical, wp_api
from core.models import Page, SeoAudit

_lock = threading.Lock()

META_MIN, META_MAX = 100, 160
TITLE_MIN, TITLE_MAX = 25, 65
WORDS_MIN = {"post": 600, "default": 120}
EXCLUDED_TYPES = {"attachment", "e-floating-buttons", "elementor_library",
                  "elementskit_content", "elementskit_template"}


# ── shared helpers ─────────────────────────────────────────────────────────

def _llm(prompt, max_chars=6000):
    import gen

    env = gen.load_env()
    data = gen._post(
        "/chat/completions",
        {"model": env.get("GROQ_MODEL", gen.DEFAULT_MODEL),
         "messages": [{"role": "user", "content": prompt[:max_chars + 2000]}],
         "temperature": 0.4},
        gen.api_key(env),
    )
    return data["choices"][0]["message"]["content"].strip()


def _truncate_meta(text):
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= META_MAX:
        return text
    cut = text[: META_MAX - 1]
    cut = cut[: cut.rindex(" ")] if " " in cut else cut
    return cut.rstrip(",;:- ") + "…"


def _generate_meta(title, content_text):
    try:
        raw = _llm(f"Write ONLY a meta description (140-155 characters, no quotes) "
                   f"for this web page titled '{title}':\n\n{content_text[:1500]}")
        return _truncate_meta(raw.strip('"'))
    except Exception:
        return _truncate_meta(content_text[:200])


def _live_page(url):
    """Fetch the real rendered page - the truth for template-driven pages."""
    result = crawler.fetch(url)
    if result.get("status") != 200:
        return None
    html = result["body"].decode("utf8", "replace")
    body = html.split("</head>", 1)[-1]
    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", body, flags=re.S | re.I)
    meta_match = re.search(r'<meta name="description" content="([^"]*)"', html)
    body_text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body)).strip()
    return {"words": len(body_text.split()), "text": body_text,
            "meta": (meta_match.group(1).strip() if meta_match else "")}


# ── content audit (WordPress items) ────────────────────────────────────────

def _content_types(env):
    types = wp.call("/types?context=edit", env=env)
    return [{"slug": slug, "base": t["rest_base"], "label": t.get("name", slug),
             "has_excerpt": "excerpt" in (t.get("supports") or {})}
            for slug, t in types.items() if t.get("viewable") and slug not in EXCLUDED_TYPES]


def _audit_item(item, ptype):
    is_post = ptype["slug"] == "post"
    title = re.sub(r"<[^>]+>", "", item.get("title", {}).get("rendered", "")) or "(untitled)"
    content = item.get("content", {}).get("rendered", "") or ""
    text = re.sub(r"<[^>]+>", " ", content)
    words = len(text.split())
    meta = re.sub(r"<[^>]+>", "", (item.get("excerpt", {}) or {}).get("raw") or "").strip()
    custom_meta = ((item.get("meta") or {}).get("servelens_seo_desc") or "").strip()
    h2s = len(re.findall(r"<h2", content, re.I))
    links = len(re.findall(r"<a\s", content, re.I))
    slug = item.get("slug", "")

    if not is_post and words < 40 and item.get("status") == "publish" and item.get("link"):
        live = _live_page(item["link"])
        if live:
            words, text = live["words"], live["text"]
            if not meta:
                meta = live["meta"] if custom_meta else ""
    if custom_meta:
        meta = custom_meta

    issues = []
    meta_field = "excerpt" if ptype["has_excerpt"] else "meta_desc"
    if not meta:
        issues.append({"code": "meta-missing", "label": "Meta description missing",
                       "detail": "Without one, Google picks its own snippet.",
                       "fix": {"field": meta_field, "value": None, "generate": True,
                               "label": "AI-written description"}})
    elif len(meta) > META_MAX:
        issues.append({"code": "meta-long", "label": f"Meta description too long ({len(meta)} chars)",
                       "detail": f"Google truncates around {META_MAX} characters.",
                       "fix": {"field": meta_field, "value": _truncate_meta(meta), "label": "Trim to fit"}})
    elif len(meta) < META_MIN:
        issues.append({"code": "meta-short", "label": f"Meta description short ({len(meta)} chars)",
                       "detail": f"{META_MIN}–{META_MAX} chars uses the full snippet.", "fix": None})
    if len(title) > TITLE_MAX:
        issues.append({"code": "title-long", "label": f"Title too long ({len(title)} chars)",
                       "detail": "Titles over ~60 characters get cut off in results.", "fix": None})
    elif len(title) < TITLE_MIN and is_post:
        issues.append({"code": "title-short", "label": f"Title short ({len(title)} chars)",
                       "detail": "Short titles waste ranking signal.", "fix": None})
    minimum = WORDS_MIN["post" if is_post else "default"]
    if words < minimum:
        issues.append({"code": "thin-content", "label": f"Thin content ({words} words)",
                       "detail": f"{minimum}+ words expected for this content type.", "fix": None})
    if is_post and h2s < 2:
        issues.append({"code": "few-headings", "label": f"Only {h2s} H2 heading(s)",
                       "detail": "Subheadings win featured snippets and keep readers.", "fix": None})
    if is_post and links == 0:
        issues.append({"code": "no-links", "label": "No links in content",
                       "detail": "At least one internal link helps crawling and dwell time.", "fix": None})
    if is_post and not (item.get("featured_media") or 0):
        issues.append({"code": "no-image", "label": "No featured image",
                       "detail": "Social shares and og:image need one.", "fix": None})
    if len(slug) > 75:
        issues.append({"code": "slug-long", "label": f"URL slug very long ({len(slug)} chars)",
                       "detail": "Short slugs are more clickable and shareable.", "fix": None})

    total_checks = 7 if is_post else 4
    return {"id": item["id"], "type": ptype["slug"], "base": ptype["base"], "title": title,
            "status": item.get("status", "publish"), "link": item.get("link"),
            "score": round(max(total_checks - len(issues), 0) / total_checks * 100), "issues": issues}


def saved_audit(site=None):
    row = SeoAudit.objects.filter(site=sites.env_for(site)["_site_id"]).first()
    if not row:
        return None
    return {"generated_at": row.generated_at.isoformat(timespec="seconds"), **row.data}


def _summarize(results):
    return {"items": len(results),
            "avg_score": round(sum(r["score"] for r in results) / len(results)) if results else 100,
            "with_issues": sum(1 for r in results if r["issues"]),
            "fixable": sum(1 for r in results for i in r["issues"] if i.get("fix"))}


def audit(force=False, site=None):
    env = sites.env_for(site)
    if not force:
        saved = saved_audit(site)
        if saved is not None:
            return saved
    results, types_found = [], []
    for ptype in _content_types(env):
        statuses = "publish,future,pending,draft" if ptype["slug"] == "post" else "publish,draft"
        try:
            items = wp.call(f"/{ptype['base']}?status={statuses}&per_page=50&context=edit", env=env)
        except RuntimeError:
            try:
                items = wp.call(f"/{ptype['base']}?per_page=50&context=edit", env=env)
            except RuntimeError:
                continue
        types_found.append({"slug": ptype["slug"], "count": len(items)})
        with ThreadPoolExecutor(max_workers=8) as pool:
            results += list(pool.map(lambda i: _audit_item(i, ptype), items))
    results.sort(key=lambda r: r["score"])
    data = {"summary": {**_summarize(results), "types": types_found}, "results": results}
    row, _ = SeoAudit.objects.update_or_create(site=env["_site_id"],
                                               defaults={"data": data, "generated_at": timezone.now()})
    return {"generated_at": row.generated_at.isoformat(timespec="seconds"), **data}


def _edit_saved(site_id, fn):
    with _lock:
        row = SeoAudit.objects.filter(site=site_id).first()
        if not row:
            return
        fn(row.data)
        row.data["summary"] = {**row.data["summary"], **_summarize(row.data["results"])}
        row.save(update_fields=["data"])


def suggest_meta(base, item_id, site=None):
    if not re.match(r"^[a-z0-9-]+$", base):
        raise ValueError(f"bad rest base: {base}")
    env = sites.env_for(site)
    saved = saved_audit(site)
    if saved:
        for r in saved["results"]:
            if r["id"] == int(item_id) and r["base"] == base:
                for issue in r["issues"]:
                    if issue.get("fix") and issue["fix"].get("value"):
                        return {"value": issue["fix"]["value"], "cached": True}
    item = wp.call(f"/{base}/{int(item_id)}?context=edit", env=env)
    title = re.sub(r"<[^>]+>", "", item.get("title", {}).get("rendered", "")) or "page"
    text = re.sub(r"<[^>]+>", " ", item.get("content", {}).get("rendered", "") or "")
    if len(text.split()) < 40 and item.get("link"):
        live = _live_page(item["link"])
        if live:
            text = live["text"]
    value = _generate_meta(title, text)

    def remember(data):
        for r in data["results"]:
            if r["id"] == int(item_id) and r["base"] == base:
                for issue in r["issues"]:
                    if issue.get("fix") and issue["fix"].get("generate"):
                        issue["fix"]["value"] = value
    _edit_saved(env["_site_id"], remember)
    return {"value": value}


def apply_fix(base, item_id, field, value, site=None, actor="dashboard"):
    """User approved a content-audit fix -> change gate -> WordPress."""
    kind = {"excerpt": "excerpt", "title": "title", "slug": "slug", "meta_desc": "meta"}.get(field)
    if not kind:
        raise ValueError(f"cannot auto-fix field: {field}")
    if not re.match(r"^[a-z0-9-]+$", base) or base not in wp_api.SAFE_BASE:
        raise ValueError(f"bad rest base: {base}")
    env = sites.env_for(site)
    change = changes.propose_and_apply(kind, base, int(item_id), value, reason="content audit fix",
                                       source="ai", site=site, actor=actor)

    def drop(data):
        for r in data["results"]:
            if r["id"] == int(item_id) and r["base"] == base:
                r["issues"] = [i for i in r["issues"] if not (i.get("fix") and i["fix"].get("field") == field)]
                total = 7 if r["type"] == "post" else 4
                r["score"] = round(max(total - len(r["issues"]), 0) / total * 100)
    _edit_saved(env["_site_id"], drop)
    return {"id": int(item_id), "applied": field, "change": change["id"]}


# ── technical audit (crawl) ────────────────────────────────────────────────

def technical_report(site=None):
    """Latest crawl analysed on demand. Analysis is milliseconds; no caching needed."""
    crawl = crawler.latest(site)
    if not crawl:
        return {"crawl": None}
    pages = list(crawl.pages.all())
    report = technical.analyze(crawl, pages) if crawl.status == "done" else {"score": None, "summary": None, "issues": [], "breakdown": {}}
    return {
        "crawl": {"id": crawl.pk, "status": crawl.status, "started_at": crawl.started_at.isoformat(timespec="seconds"),
                  "finished_at": crawl.finished_at.isoformat(timespec="seconds") if crawl.finished_at else None,
                  "pages_total": crawl.pages_total, "sitemap_url": crawl.sitemap_url, "note": crawl.note},
        "score": report.get("score"),
        "summary": report.get("summary"),
        "breakdown": report.get("breakdown"),
        "issues": report.get("issues"),
        "pages": [{"id": p.pk, "url": p.url, "status": p.status_code, "title": p.title, "words": p.word_count,
                   "score": report.get("page_scores", {}).get(p.url), "wp_base": p.wp_base, "wp_id": p.wp_id,
                   "issues": len(report.get("per_page", {}).get(p.url, []))}
                  for p in sorted(pages, key=lambda p: report.get("page_scores", {}).get(p.url, 100))],
    }


def page_detail(page_id, site=None):
    page = Page.objects.select_related("crawl").filter(pk=page_id).first()
    if not page:
        raise KeyError(page_id)
    report = technical.analyze(page.crawl, list(page.crawl.pages.all()))
    return {
        "id": page.pk, "url": page.url, "final_url": page.final_url, "status": page.status_code,
        "title": page.title, "meta_description": page.meta_description, "h1": page.h1,
        "h2_count": page.h2_count, "word_count": page.word_count, "canonical": page.canonical,
        "meta_robots": page.meta_robots, "in_sitemap": page.in_sitemap, "depth": page.depth,
        "response_ms": page.response_ms, "jsonld_types": page.jsonld_types,
        "internal_links": len(page.internal_links), "external_links": len(page.external_links),
        "wp_base": page.wp_base, "wp_id": page.wp_id,
        "score": report["page_scores"].get(page.url), "issues": report["per_page"].get(page.url, []),
    }


ONPAGE_PROMPT = """You are an SEO editor. Rewrite the on-page basics for this web page.

URL: {url}
Current <title>: {title}
Current meta description: {meta}
Current H1: {h1}
Page text (excerpt): {text}

Rules:
- title: 30-60 characters, primary topic first, no clickbait, no site name.
- meta_description: 120-155 characters, plain sentence, states the benefit, no quotes.
- h1: 20-70 characters, names the topic the page is actually about; may match the title.
- primary_keyword: the 2-5 word phrase the page should rank for.
- reason: one sentence on what was wrong and why the new versions are better.
Reply with ONLY this JSON object:
{{"title": "...", "meta_description": "...", "h1": "...", "primary_keyword": "...", "reason": "..."}}"""


def suggest_onpage(page_id, site=None):
    """AI title / meta / H1 for a crawled page. Suggest only - nothing is written."""
    page = Page.objects.filter(pk=page_id).first()
    if not page:
        raise KeyError(page_id)
    raw = _llm(ONPAGE_PROMPT.format(url=page.url, title=page.title or "(none)",
                                    meta=page.meta_description or "(none)",
                                    h1=", ".join(page.h1) or "(none)", text=page.text_sample[:2500]))
    match = re.search(r"\{.*\}", raw, re.S)
    if not match:
        raise RuntimeError("model returned no JSON")
    data = json.loads(match.group(0))
    out = {k: (data.get(k) or "").strip().strip('"') for k in ("title", "meta_description", "h1", "primary_keyword", "reason")}
    out["meta_description"] = _truncate_meta(out["meta_description"])
    out["can_apply"] = bool(page.wp_base and page.wp_id)
    return out


def apply_onpage(page_id, field, value, site=None, actor="dashboard"):
    """Approved suggestion -> WordPress through the change gate (logged, rollback-able).
    H1 on posts IS the title (theme renders it); on template pages it is suggest-only."""
    page = Page.objects.filter(pk=page_id).first()
    if not page:
        raise KeyError(page_id)
    if not (page.wp_base and page.wp_id):
        raise ValueError("this URL is not mapped to a WordPress item - edit it in the theme instead")
    if field not in ("title", "meta_description", "h1"):
        raise ValueError(f"cannot apply field: {field}")
    if field == "h1" and page.wp_base != "posts":
        raise ValueError("H1 on this page comes from the template - suggestion only")
    kind = {"title": "title", "h1": "h1", "meta_description": "meta"}[field]
    change = changes.propose_and_apply(kind, page.wp_base, page.wp_id, value, reason="on-page suggestion",
                                       source="ai", site=site, actor=actor)
    # keep the crawl row honest until the next crawl
    if field == "meta_description":
        page.meta_description = value
    else:
        page.title = value if field == "title" else page.title
        page.h1 = [value] if field == "h1" or page.wp_base == "posts" else page.h1
    page.save(update_fields=["title", "h1", "meta_description"])
    return {"applied": field, "change": change["id"], "wp_field": change["field"]}


def invalidate():
    """Kept for callers; saved audits stay until the user re-runs one."""
