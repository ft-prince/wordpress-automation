"""Site-wide SEO audit: posts, pages, and custom post types, with approvable fixes.
Deterministic fixes computed here; missing meta descriptions written by Groq."""
import re
import threading
import time

import wp
from core import sites, wp_api

_TTL_SECONDS = 120
_cache = {}
_lock = threading.Lock()

META_MIN, META_MAX = 100, 160
TITLE_MIN, TITLE_MAX = 25, 65
# Blog posts should be substantial; landing pages just shouldn't be empty.
WORDS_MIN = {"post": 600, "default": 120}
EXCLUDED_TYPES = {"attachment", "e-floating-buttons", "elementor_library",
                  "elementskit_content", "elementskit_template"}


def _content_types(env):
    """Viewable public types straight from WP — new CPTs show up automatically."""
    types = wp.call("/types?context=edit", env=env)
    found = []
    for slug, t in types.items():
        if t.get("viewable") and slug not in EXCLUDED_TYPES:
            found.append({
                "slug": slug,
                "base": t["rest_base"],
                "label": t.get("name", slug),
                "has_excerpt": "excerpt" in (t.get("supports") or {}),
            })
    return found


def _truncate_meta(text):
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= META_MAX:
        return text
    cut = text[: META_MAX - 1]
    cut = cut[: cut.rindex(" ")] if " " in cut else cut
    return cut.rstrip(",;:—- ") + "…"


def _generate_meta(title, content_text):
    try:
        import gen

        env = gen.load_env()
        data = gen._post(
            "/chat/completions",
            {
                "model": env.get("GROQ_MODEL", gen.DEFAULT_MODEL),
                "messages": [{
                    "role": "user",
                    "content": f"Write ONLY a meta description (140-155 characters, no quotes) "
                               f"for this web page titled '{title}':\n\n{content_text[:1500]}",
                }],
            },
            gen.api_key(env),
        )
        return _truncate_meta(data["choices"][0]["message"]["content"].strip().strip('"'))
    except Exception:
        return _truncate_meta(content_text[:200])


def _live_page(url):
    """Fetch the real rendered page — the truth for template-driven pages."""
    import urllib.request

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (seo-audit)"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            html = resp.read(500_000).decode("utf8", "replace")
    except Exception:
        return None
    body = html.split("</head>", 1)[-1]
    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", body, flags=re.S | re.I)
    meta_match = re.search(r'<meta name="description" content="([^"]*)"', html)
    body_text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body)).strip()
    return {
        "words": len(body_text.split()),
        "text": body_text,
        "meta": (meta_match.group(1).strip() if meta_match else ""),
    }


def _audit_item(item, ptype):
    is_post = ptype["slug"] == "post"
    title = re.sub(r"<[^>]+>", "", item.get("title", {}).get("rendered", "")) or "(untitled)"
    content = item.get("content", {}).get("rendered", "") or ""
    text = re.sub(r"<[^>]+>", " ", content)
    words = len(text.split())
    excerpt_raw = item.get("excerpt", {}) or {}
    meta = re.sub(r"<[^>]+>", "", excerpt_raw.get("raw") or "").strip()
    custom_meta = ((item.get("meta") or {}).get("servelens_seo_desc") or "").strip()
    h2s = len(re.findall(r"<h2", content, re.I))
    links = len(re.findall(r"<a\s", content, re.I))
    slug = item.get("slug", "")
    live = None

    # Template/Elementor pages keep post_content empty — judge the live page instead.
    if not is_post and words < 40 and item.get("status") == "publish" and item.get("link"):
        live = _live_page(item["link"])
        if live:
            words = live["words"]
            text = live["text"]
            if not meta:
                meta = live["meta"] if custom_meta else ""  # only trust hand-set values
    if custom_meta:
        meta = custom_meta

    issues = []

    meta_field = "excerpt" if ptype["has_excerpt"] else "meta_desc"
    if not meta:
        issues.append({
            "code": "meta-missing", "label": "Meta description missing",
            "detail": "Without one, Google picks its own snippet.",
            "fix": {"field": meta_field, "value": None, "generate": True,
                    "label": "AI-written description"},
        })
    elif len(meta) > META_MAX:
        issues.append({
            "code": "meta-long", "label": f"Meta description too long ({len(meta)} chars)",
            "detail": f"Google truncates around {META_MAX} characters.",
            "fix": {"field": meta_field, "value": _truncate_meta(meta), "label": "Trim to fit"},
        })
    elif len(meta) < META_MIN:
        issues.append({
            "code": "meta-short", "label": f"Meta description short ({len(meta)} chars)",
            "detail": f"{META_MIN}–{META_MAX} chars uses the full snippet.", "fix": None,
        })

    if len(title) > TITLE_MAX:
        issues.append({
            "code": "title-long", "label": f"Title too long ({len(title)} chars)",
            "detail": "Titles over ~60 characters get cut off in results.", "fix": None,
        })
    elif len(title) < TITLE_MIN and is_post:
        issues.append({
            "code": "title-short", "label": f"Title short ({len(title)} chars)",
            "detail": "Short titles waste ranking signal.", "fix": None,
        })

    minimum = WORDS_MIN["post" if is_post else "default"]
    if words < minimum:
        issues.append({
            "code": "thin-content", "label": f"Thin content ({words} words)",
            "detail": f"{minimum}+ words expected for this content type.", "fix": None,
        })
    if is_post and h2s < 2:
        issues.append({
            "code": "few-headings", "label": f"Only {h2s} H2 heading(s)",
            "detail": "Subheadings win featured snippets and keep readers.", "fix": None,
        })
    if is_post and links == 0:
        issues.append({
            "code": "no-links", "label": "No links in content",
            "detail": "At least one internal link helps crawling and dwell time.", "fix": None,
        })
    if is_post and not (item.get("featured_media") or 0):
        issues.append({
            "code": "no-image", "label": "No featured image",
            "detail": "Social shares and og:image need one.", "fix": None,
        })
    if len(slug) > 75:
        issues.append({
            "code": "slug-long", "label": f"URL slug very long ({len(slug)} chars)",
            "detail": "Short slugs are more clickable and shareable.", "fix": None,
        })

    total_checks = 7 if is_post else 4
    score = round(max(total_checks - len(issues), 0) / total_checks * 100)
    return {
        "id": item["id"], "type": ptype["slug"], "base": ptype["base"],
        "title": title, "status": item.get("status", "publish"),
        "link": item.get("link"), "score": score, "issues": issues,
    }


def audit(force=False, site=None):
    env = sites.env_for(site)
    cache_key = env["_site_id"]
    with _lock:
        hit = _cache.get(cache_key)
        if not force and hit and time.time() - hit["at"] < _TTL_SECONDS:
            return hit["data"]

    from concurrent.futures import ThreadPoolExecutor

    results = []
    types_found = []
    for ptype in _content_types(env):
        # Draft statuses only make sense for the queryable types; pages/CPTs audit published.
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
    summary = {
        "items": len(results),
        "types": types_found,
        "avg_score": round(sum(r["score"] for r in results) / len(results)) if results else 100,
        "with_issues": sum(1 for r in results if r["issues"]),
        "fixable": sum(1 for r in results for i in r["issues"] if i["fix"]),
    }
    data = {"summary": summary, "results": results}
    with _lock:
        _cache[cache_key] = {"at": time.time(), "data": data}
    return data


def suggest_meta(base, item_id, site=None):
    """Generate a meta description for one item, on demand."""
    if not re.match(r"^[a-z0-9-]+$", base):
        raise ValueError(f"bad rest base: {base}")
    item = wp.call(f"/{base}/{int(item_id)}?context=edit", env=sites.env_for(site))
    title = re.sub(r"<[^>]+>", "", item.get("title", {}).get("rendered", "")) or "page"
    text = re.sub(r"<[^>]+>", " ", item.get("content", {}).get("rendered", "") or "")
    if len(text.split()) < 40 and item.get("link"):
        live = _live_page(item["link"])
        if live:
            text = live["text"]
    return {"value": _generate_meta(title, text)}


def apply_fix(base, item_id, field, value, site=None):
    """User approved a fix — write it to the item, whatever its type."""
    if field not in ("excerpt", "title", "slug", "meta_desc"):
        raise ValueError(f"cannot auto-fix field: {field}")
    if not re.match(r"^[a-z0-9-]+$", base):
        raise ValueError(f"bad rest base: {base}")
    payload = {"meta": {"servelens_seo_desc": value}} if field == "meta_desc" else {field: value}
    result = wp.call(f"/{base}/{int(item_id)}?context=edit", payload, method="POST", env=sites.env_for(site))
    if field == "meta_desc":
        saved = (result.get("meta") or {}).get("servelens_seo_desc", "")
        if saved != value:
            raise RuntimeError("WordPress ignored this field. Upload servelens-seo.php v1.1 to mu-plugins first")
    wp_api.invalidate()
    invalidate()
    return {"id": result["id"], "applied": field}


def invalidate():
    with _lock:
        _cache.clear()
