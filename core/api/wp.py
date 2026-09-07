"""WordPress proxy: posts, items, terms, theme files, generation."""
import urllib.parse

from ninja import Router, Schema
from ninja.errors import HttpError

from core import roles, sites, store, wp_api

router = Router()


class PostFields(Schema):
    title: str | None = None
    content: str | None = None
    excerpt: str | None = None
    slug: str | None = None
    status: str | None = None
    date_gmt: str | None = None
    categories: list[int] | None = None
    tags: list[int] | None = None


class ItemFields(Schema):
    title: str | None = None
    content: str | None = None
    excerpt: str | None = None
    slug: str | None = None
    status: str | None = None
    meta_desc: str | None = None


class ImageUrl(Schema):
    url: str


class ImageGen(Schema):
    subject: str | None = None


class TermCreate(Schema):
    kind: str
    name: str


class BulkRequest(Schema):
    ids: list[int]
    action: str
    value: str | None = None


class StatusChange(Schema):
    status: str


class ThemeFileBody(Schema):
    path: str
    content: str = ""


class GenerateRequest(Schema):
    topic: str
    words: int = 800


def _set(body):
    return {k: v for k, v in body.dict().items() if v is not None}


@router.get("/wp/health")
def wp_health(request, site: str | None = None):
    return wp_api.health(site)


@router.get("/wp/posts")
def wp_posts(request, status: str = "publish", limit: int = 10, search: str = "",
             page: int = 1, category: int | None = None, site: str | None = None):
    return wp_api.posts(status, min(limit, 50), search, max(page, 1), category, site=site)


@router.post("/wp/posts")
def wp_create_post(request, body: PostFields, site: str | None = None):
    fields = _set(body)
    fields.setdefault("status", "draft")
    result = wp_api.create_post(fields, site=site)
    store.add_audit("dashboard", "post-create", f"wp:{result['id']}", None, {"title": result["title"]})
    return result


@router.post("/wp/posts/bulk")
def wp_bulk(request, body: BulkRequest, site: str | None = None):
    if not body.ids:
        raise HttpError(400, "no posts selected")
    if body.action in ("publish", "trash", "delete", "reschedule"):
        roles.require(request, "delete" if body.action == "delete" else "publish")
    results = wp_api.bulk(body.ids, body.action, body.value, site=site)
    ok = sum(1 for r in results if r["ok"])
    store.add_audit("dashboard", f"bulk-{body.action}", f"{ok}/{len(results)} posts")
    return {"results": results, "ok": ok, "failed": len(results) - ok}


@router.get("/wp/posts/{post_id}")
def wp_post_detail(request, post_id: int, site: str | None = None):
    return wp_api.get_post(post_id, site=site)


@router.patch("/wp/posts/{post_id}")
def wp_update_post(request, post_id: int, body: PostFields, site: str | None = None):
    fields = _set(body)
    if not fields:
        raise HttpError(400, "nothing to change")
    result = wp_api.update_post(post_id, fields, site=site)
    store.add_audit("dashboard", "post-update", f"wp:{post_id}", None, {"fields": list(fields)})
    return result


@router.delete("/wp/posts/{post_id}")
def wp_delete_post(request, post_id: int, force: bool = False, site: str | None = None):
    roles.require(request, "delete" if force else "publish")
    result = wp_api.delete_post(post_id, force, site=site)
    store.add_audit("dashboard", "post-delete" + ("-forever" if force else ""), f"wp:{post_id}")
    return result


@router.post("/wp/posts/{post_id}/restore")
def wp_restore_post(request, post_id: int, site: str | None = None):
    result = wp_api.restore_post(post_id, site=site)
    store.add_audit("dashboard", "post-restore", f"wp:{post_id}")
    return result


@router.get("/wp/posts/{post_id}/revisions")
def wp_revisions(request, post_id: int, site: str | None = None):
    return wp_api.revisions(post_id, site=site)


@router.post("/wp/posts/{post_id}/featured")
def wp_featured(request, post_id: int, body: ImageUrl, site: str | None = None):
    result = wp_api.set_featured_from_url(post_id, body.url, site=site)
    store.add_audit("dashboard", "post-featured-image", f"wp:{post_id}")
    return result


@router.post("/wp/posts/{post_id}/featured/generate")
def generate_featured(request, post_id: int, body: ImageGen = None, site: str | None = None):
    """AI featured image: generate, upload to WP media, attach."""
    from core import images

    subject = body.subject if body and body.subject else None
    if not subject:
        subject = wp_api.get_post(post_id, site=site)["title"]
    media_id = images.set_featured(post_id, subject, site=site)
    store.add_audit("dashboard", "featured-image-generated", f"wp:{post_id}")
    return {"media_id": media_id}


@router.post("/wp/posts/{post_id}/status")
def wp_set_status(request, post_id: int, body: StatusChange, site: str | None = None):
    if body.status == "publish":
        roles.require(request, "publish")
    result = wp_api.set_status(post_id, body.status, site=site)
    store.add_audit("dashboard", f"post-{body.status}", f"wp:{post_id}")
    return result


@router.get("/wp/terms")
def wp_terms(request, site: str | None = None):
    return wp_api.terms(site=site)


@router.post("/wp/terms")
def wp_create_term(request, body: TermCreate, site: str | None = None):
    return wp_api.create_term(body.kind, body.name, site=site)


@router.get("/wp/items/{base}/{item_id}")
def wp_item(request, base: str, item_id: int, site: str | None = None):
    return wp_api.get_item(base, item_id, site=site)


@router.patch("/wp/items/{base}/{item_id}")
def wp_item_update(request, base: str, item_id: int, body: ItemFields, site: str | None = None):
    fields = _set(body)
    if not fields:
        raise HttpError(400, "nothing to change")
    result = wp_api.update_item(base, item_id, fields, site=site)
    store.add_audit("dashboard", "item-update", f"{base}:{item_id}", None, {"fields": list(fields)})
    return result


def _theme_call(path, site, payload=None, method="GET"):
    import wp as wp_mod

    env = sites.env_for(site)
    try:
        return wp_mod.call_ns(path, payload, method=method, env=env)
    except RuntimeError as exc:
        msg = str(exc)
        if "404" in msg and "rest_no_route" in msg:
            raise HttpError(502, "This site is running an older helper plugin. "
                                 "Upload servelens-seo.php v1.2 to wp-content/mu-plugins first")
        raise HttpError(502, msg[:300])


@router.get("/theme/files")
def theme_files(request, site: str | None = None):
    return _theme_call("/automation/v1/theme-files", site)


@router.get("/theme/file")
def theme_file(request, path: str, site: str | None = None):
    return _theme_call(f"/automation/v1/theme-file?path={urllib.parse.quote(path)}", site)


@router.post("/theme/file")
def theme_file_save(request, body: ThemeFileBody, site: str | None = None):
    result = _theme_call("/automation/v1/theme-file", site,
                         {"path": body.path, "content": body.content}, method="POST")
    store.add_audit("dashboard", "theme-file-save", body.path, None, {"bytes": len(body.content)})
    return result


@router.delete("/theme/file")
def theme_file_delete(request, path: str, site: str | None = None):
    result = _theme_call(f"/automation/v1/theme-file?path={urllib.parse.quote(path)}", site,
                         method="DELETE")
    store.add_audit("dashboard", "theme-file-delete", path)
    return result


@router.post("/generate")
def generate_content(request, body: GenerateRequest):
    """Groq research + write. Returns title/html without touching WordPress."""
    import gen

    if not body.topic.strip():
        raise HttpError(400, "topic is required")
    try:
        title, meta, html, keywords = gen.write_full(body.topic, words=min(max(body.words, 200), 2500))
    except (RuntimeError, SystemExit) as exc:
        raise HttpError(502, f"generation failed: {exc}")
    return {"title": title, "content": html, "excerpt": meta, "keywords": keywords}
