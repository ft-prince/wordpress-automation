"""WordPress content state for the dashboard. Cached so polling never hammers the site."""
import threading
import time
import urllib.parse
import urllib.request

import wp
from core import sites

_TTL_SECONDS = 30
_cache = {}
_lock = threading.Lock()
_last_ok = {"at": None, "latency_ms": None}
_last_fail = {"at": None, "error": None}
MAX_IMAGE_BYTES = 8 * 1024 * 1024

ALL_STATUSES = ("publish", "future", "draft", "pending", "private", "trash")
# Fields a dashboard edit may touch. Everything else is rejected at this boundary.
EDITABLE_FIELDS = ("title", "content", "excerpt", "slug", "status", "date_gmt",
                   "categories", "tags", "featured_media", "author")


_refreshing = set()


def _cached(key, fetch):
    """Stale-while-revalidate: expired entries are served instantly and refreshed
    in a background thread, so dashboard polling never blocks on WordPress."""
    with _lock:
        hit = _cache.get(key)
        if hit:
            if time.time() - hit[0] < _TTL_SECONDS:
                return hit[1]
            if key not in _refreshing:
                _refreshing.add(key)
                threading.Thread(target=_refresh, args=(key, fetch), daemon=True).start()
            return hit[1]  # stale but instant; fresh value lands on the next poll
    value = fetch()
    with _lock:
        _cache[key] = (time.time(), value)
    return value


def _refresh(key, fetch):
    try:
        value = fetch()
        with _lock:
            _cache[key] = (time.time(), value)
    except Exception:
        pass  # keep serving the stale value; next expiry retries
    finally:
        with _lock:
            _refreshing.discard(key)


def invalidate():
    with _lock:
        _cache.clear()


def _slim(post, env=None):
    """Flatten a WP post + _embedded into what the dashboard needs. Nothing more."""
    env = env or sites.env_for()
    embedded = post.get("_embedded", {})
    author = (embedded.get("author") or [{}])[0]
    media = (embedded.get("wp:featuredmedia") or [{}])[0]
    terms = embedded.get("wp:term") or []
    import re as _re

    excerpt_raw = post.get("excerpt", {})
    excerpt = _re.sub(r"<[^>]+>", "", excerpt_raw.get("raw") or excerpt_raw.get("rendered") or "").strip()
    title_text = post["title"]["rendered"] or "(untitled)"
    return {
        "id": post["id"],
        "title": title_text,
        # Enough signal for a list-row SEO chip without shipping full content.
        "seo": {
            "meta_ok": 100 <= len(excerpt) <= 170,
            "meta_len": len(excerpt),
            "title_ok": 25 <= len(title_text) <= 65,
        },
        "status": post["status"],
        "date_gmt": post.get("date_gmt"),
        "modified_gmt": post.get("modified_gmt"),
        "author": author.get("name", "?"),
        "categories": [t["name"] for t in (terms[0] if len(terms) > 0 else [])],
        "tags": [t["name"] for t in (terms[1] if len(terms) > 1 else [])],
        "featured_image": media.get("source_url"),
        "link": post.get("link"),
        # Draft/future preview needs a logged-in wp-admin session in the same browser.
        "preview_url": f"{env['WEBSITE_LINK'].rstrip('/')}/?p={post['id']}&preview=true",
        "edit_url": f"{env['WEBSITE_LINK'].rstrip('/')}/wp-admin/post.php?post={post['id']}&action=edit",
    }


def posts(status="publish", limit=10, search="", page=1, category=None, order=None, site=None):
    for s in status.split(","):
        if s not in ALL_STATUSES:
            raise ValueError(f"bad status: {s}")
    order = order or ("asc" if status == "future" else "desc")
    query = f"/posts?status={status}&per_page={limit}&page={page}&orderby=date&order={order}&_embed=1"
    if search:
        query += f"&search={urllib.parse.quote(search)}"
    if category:
        query += f"&categories={int(category)}"

    env = sites.env_for(site)

    def fetch():
        return [_slim(p, env) for p in wp.call(query + "&context=edit", env=env)]

    # Searches and filtered views bypass the cache — they must reflect edits instantly.
    if search or category or page > 1:
        return fetch()
    return _cached(f"{env['_site_id']}:posts:{status}:{limit}:{order}", fetch)


def get_post(post_id, site=None):
    """Full editable post for the editor drawer: raw content, term ids, slug."""
    env = sites.env_for(site)
    p = wp.call(f"/posts/{int(post_id)}?context=edit&_embed=1", env=env)
    return {
        **_slim(p, env),
        "content_raw": p.get("content", {}).get("raw", ""),
        "excerpt_raw": p.get("excerpt", {}).get("raw", ""),
        "slug": p.get("slug"),
        "category_ids": p.get("categories", []),
        "tag_ids": p.get("tags", []),
        "featured_media_id": p.get("featured_media") or 0,
    }


def _clean_fields(fields):
    rejected = [k for k in fields if k not in EDITABLE_FIELDS]
    if rejected:
        raise ValueError(f"not editable: {', '.join(rejected)}")
    if "status" in fields and fields["status"] not in ALL_STATUSES:
        raise ValueError(f"bad status: {fields['status']}")
    return fields


def create_post(fields, site=None):
    if not (fields.get("title") or "").strip():
        raise ValueError("title is required")
    env = sites.env_for(site)
    result = wp.call("/posts?context=edit", _clean_fields(fields), method="POST", env=env)
    invalidate()
    return _slim(result, env)


def update_post(post_id, fields, site=None):
    env = sites.env_for(site)
    fields = dict(_clean_fields(fields))
    # Publishing a scheduled post: WP reverts to `future` unless the date moves to now.
    if fields.get("status") == "publish" and "date_gmt" not in fields:
        current = wp.call(f"/posts/{int(post_id)}?context=edit", env=env)
        if current.get("status") == "future":
            fields["date_gmt"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    result = wp.call(f"/posts/{int(post_id)}?context=edit", fields, method="POST", env=env)
    invalidate()
    return _slim(result, env)


def delete_post(post_id, force=False, site=None):
    result = wp.call(f"/posts/{int(post_id)}?force={'true' if force else 'false'}", method="DELETE",
                     env=sites.env_for(site))
    invalidate()
    return {"deleted": True, "forced": force, "id": int(post_id)}


def restore_post(post_id, site=None):
    """Un-trash by flipping status back to draft."""
    env = sites.env_for(site)
    result = wp.call(f"/posts/{int(post_id)}?context=edit", {"status": "draft"}, method="POST", env=env)
    invalidate()
    return _slim(result, env)


def revisions(post_id, site=None):
    rows = wp.call(f"/posts/{int(post_id)}/revisions?per_page=10", env=sites.env_for(site))
    return [
        {"id": r["id"], "modified": r.get("modified_gmt"), "author": r.get("author"),
         "title": r.get("title", {}).get("rendered", "")}
        for r in rows
    ]


def terms(site=None):
    env = sites.env_for(site)

    def fetch():
        cats = wp.call("/categories?per_page=100&hide_empty=false", env=env)
        tags = wp.call("/tags?per_page=100&hide_empty=false", env=env)
        slim = lambda t: {"id": t["id"], "name": t["name"], "count": t.get("count", 0)}
        return {"categories": [slim(t) for t in cats], "tags": [slim(t) for t in tags]}

    return _cached(f"{env['_site_id']}:terms", fetch)


def ensure_category(name, site=None):
    """Find or create a category by name. Returns its id."""
    for c in terms(site)["categories"]:
        if c["name"].lower() == name.lower():
            return c["id"]
    return create_term("categories", name, site=site)["id"]


def create_term(kind, name, site=None):
    if kind not in ("categories", "tags"):
        raise ValueError("kind must be categories or tags")
    if not (name or "").strip():
        raise ValueError("name is required")
    result = wp.call(f"/{kind}", {"name": name.strip()}, method="POST", env=sites.env_for(site))
    invalidate()
    return {"id": result["id"], "name": result["name"]}


def set_featured_from_url(post_id, image_url, site=None):
    """Sideload an image URL into the media library and set it as featured."""
    if not image_url.startswith(("http://", "https://")):
        raise ValueError("image url must be http(s)")
    req = urllib.request.Request(image_url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        content_type = resp.headers.get("Content-Type", "image/jpeg").split(";")[0]
        if not content_type.startswith("image/"):
            raise ValueError(f"url is not an image ({content_type})")
        data = resp.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("image exceeds 8 MB limit")
    ext = content_type.split("/")[-1].replace("jpeg", "jpg")
    media = wp.upload_media(data, f"post-{post_id}-featured.{ext}", content_type, env=sites.env_for(site))
    result = update_post(post_id, {"featured_media": media["id"]}, site=site)
    return {**result, "media_id": media["id"]}


SAFE_BASE = ("posts", "pages", "solution")


def get_item(base, item_id, site=None):
    """Any content type, one editable payload for the universal editor."""
    if base not in SAFE_BASE:
        raise ValueError(f"unsupported type: {base}")
    env = sites.env_for(site)
    p = wp.call(f"/{base}/{int(item_id)}?context=edit", env=env)
    content_raw = (p.get("content") or {}).get("raw", "")
    word_count = len(content_raw.split())
    return {
        "id": p["id"],
        "base": base,
        "title": (p.get("title") or {}).get("raw", "") or (p.get("title") or {}).get("rendered", ""),
        "slug": p.get("slug", ""),
        "status": p.get("status"),
        "link": p.get("link"),
        "content_raw": content_raw,
        # Empty content on a live page means a builder or theme template owns the layout.
        "builder_managed": word_count < 20 and p.get("status") == "publish",
        "supports_excerpt": "excerpt" in p,
        "excerpt_raw": ((p.get("excerpt") or {}).get("raw", "") if "excerpt" in p else ""),
        "meta_desc": ((p.get("meta") or {}).get("servelens_seo_desc") or ""),
        "template": p.get("template") or "",
        "edit_url": f"{env['WEBSITE_LINK'].rstrip('/')}/wp-admin/post.php?post={p['id']}&action=edit",
    }


ITEM_FIELDS = ("title", "content", "excerpt", "slug", "status", "meta_desc")


def update_item(base, item_id, fields, site=None):
    if base not in SAFE_BASE:
        raise ValueError(f"unsupported type: {base}")
    rejected = [k for k in fields if k not in ITEM_FIELDS]
    if rejected:
        raise ValueError(f"not editable: {', '.join(rejected)}")
    env = sites.env_for(site)
    payload = {k: v for k, v in fields.items() if k != "meta_desc"}
    if "meta_desc" in fields:
        payload["meta"] = {"servelens_seo_desc": fields["meta_desc"]}
    result = wp.call(f"/{base}/{int(item_id)}?context=edit", payload, method="POST", env=env)
    if "meta_desc" in fields:
        saved = (result.get("meta") or {}).get("servelens_seo_desc", "")
        if saved != fields["meta_desc"]:
            raise RuntimeError("WordPress ignored the description field. Upload servelens-seo.php v1.1 to mu-plugins first")
    invalidate()
    return {"id": result["id"], "saved": True}


def bulk(ids, action, value=None, site=None):
    """Apply one action to many posts. Per-post errors don't stop the batch."""
    results = []
    for pid in ids[:50]:
        try:
            if action == "publish":
                update_post(pid, {"status": "publish"}, site=site)
            elif action == "approve":
                update_post(pid, {"status": "pending"}, site=site)
            elif action == "draft":
                update_post(pid, {"status": "draft"}, site=site)
            elif action == "trash":
                delete_post(pid, force=False, site=site)
            elif action == "delete":
                delete_post(pid, force=True, site=site)
            elif action == "restore":
                restore_post(pid, site=site)
            elif action == "category":
                update_post(pid, {"categories": [int(value)]}, site=site)
            elif action == "reschedule":
                update_post(pid, {"status": "future", "date_gmt": value}, site=site)
            else:
                raise ValueError(f"unknown action: {action}")
            results.append({"id": pid, "ok": True})
        except Exception as exc:
            results.append({"id": pid, "ok": False, "error": str(exc)[:150]})
    invalidate()
    return results


def health(site=None):
    """One authenticated round-trip, timed. Remembers the last success."""
    site_env = sites.env_for(site)

    def fetch():
        env = site_env
        started = time.time()
        try:
            me = wp.call("/users/me?context=edit", env=env)
            latency = int((time.time() - started) * 1000)
            _last_ok.update(at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), latency_ms=latency)
            return {
                "connected": True,
                "site": env["WEBSITE_LINK"],
                "user": me.get("name") or me["slug"],
                "roles": me.get("roles", []),
                "auth": "application-password",
                "latency_ms": latency,
                "last_ok": _last_ok["at"],
                "last_fail": dict(_last_fail),
                "error": None,
            }
        except Exception as exc:
            _last_fail.update(at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), error=str(exc)[:200])
            return {
                "connected": False,
                "site": env.get("WEBSITE_LINK"),
                "user": None,
                "roles": [],
                "auth": "application-password",
                "latency_ms": None,
                "last_ok": _last_ok["at"],
                "last_fail": dict(_last_fail),
                "error": str(exc)[:200],
            }

    return _cached(f"{site_env['_site_id']}:health", fetch)


def set_status(post_id, status, site=None):
    """Approve/publish/schedule from the dashboard. WP validates the transition."""
    if status not in ("publish", "future", "draft", "pending"):
        raise ValueError(f"bad status: {status}")
    env = sites.env_for(site)
    result = wp.call(f"/posts/{int(post_id)}", {"status": status}, method="POST", env=env)
    invalidate()
    return _slim({**result, "_embedded": result.get("_embedded", {})}, env)
