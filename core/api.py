"""FastAPI control plane. Keep the surface exactly as small as claude.md §3 defines."""
import asyncio
import os
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core import registry, runner, scheduler, secrets, sites, store, wp_api

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dashboard", "dist")
POLL_SECONDS = 0.7


@asynccontextmanager
async def lifespan(_app):
    store.init()
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title="Automation control plane", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


from core import auth as dash_auth


class LoginRequest(BaseModel):
    username: str = ""
    password: str


@app.get("/api/auth/status")
def auth_status():
    return {"needs_setup": dash_auth.needs_setup()}


@app.post("/api/setup")
def setup_account(body: LoginRequest):
    try:
        token = dash_auth.create_account(body.username, body.password)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    store.add_audit("dashboard", "account-created", body.username)
    return {"token": token}


@app.post("/api/login")
def login(body: LoginRequest):
    if not dash_auth.verify(body.username, body.password):
        raise HTTPException(401, "wrong username or password")
    return {"token": dash_auth.issue()}


@app.post("/api/logout")
def logout(request: Request):
    dash_auth.logout(request.headers.get("x-auth-token", ""))
    return {"ok": True}


PUBLIC_PATHS = {"/api/login", "/api/setup", "/api/auth/status"}


@app.middleware("http")
async def require_auth(request: Request, call_next):
    """Every /api route outside PUBLIC_PATHS needs a valid session. Static SPA stays open."""
    path = request.url.path
    if path.startswith("/api") and path not in PUBLIC_PATHS:
        if not dash_auth.check(request.headers.get("x-auth-token", "")):
            from fastapi.responses import JSONResponse

            return JSONResponse({"detail": "unauthorized"}, status_code=401)
    return await call_next(request)


class SiteCreate(BaseModel):
    id: str
    name: str
    url: str
    user: str
    password: str


@app.get("/api/sites")
def list_sites():
    return {"sites": sites.all_sites(), "default": sites.default_id()}


@app.post("/api/sites")
def add_site(body: SiteCreate):
    try:
        result = sites.add(body.id, body.name, body.url, body.user, body.password)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    store.add_audit("dashboard", "site-added", body.id, None, {"url": body.url})
    return result


class SiteTest(BaseModel):
    url: str
    user: str
    password: str


@app.post("/api/sites/test")
def test_site(body: SiteTest):
    return sites.test(body.url, body.user, body.password)


@app.delete("/api/sites/{site_id}")
def remove_site(site_id: str):
    try:
        sites.remove(site_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    wp_api.invalidate()
    store.add_audit("dashboard", "site-removed", site_id)
    return {"removed": True}


class Patch(BaseModel):
    name: str | None = None
    description: str | None = None
    schedule: str | None = None
    enabled: bool | None = None
    timeout_seconds: int | None = None
    args: dict | None = None
    tags: list[str] | None = None
    alert_on_failure: bool | None = None


class Source(BaseModel):
    body: str


class RunRequest(BaseModel):
    dry_run: bool = False


class SecretValue(BaseModel):
    value: str


def _decorate(job):
    """Registry entry + live state. The registry stays the source of truth."""
    last = store.last_run(job["id"])
    current_step = None
    if last and last["status"] == "running":
        lines = store.logs(last["id"])
        if lines:
            current_step = lines[-1]["line"][:120]
    return {
        **job,
        "last_run": last,
        "next_run": scheduler.next_run(job["id"]),
        "status": (last or {}).get("status", "never"),
        "current_step": current_step,
    }


@app.get("/api/jobs")
def list_jobs():
    return [_decorate(j) for j in registry.all_jobs()]


@app.get("/api/jobs/{job_id}")
def job_detail(job_id: str):
    try:
        job = registry.get(job_id)
    except (KeyError, ValueError):
        raise HTTPException(404, "no such job")
    return {
        **_decorate(job),
        "yaml": registry.raw(job_id),
        "source": registry.source(job_id),
        "durations": store.recent_durations(job_id),
        "runs": store.runs(job_id, limit=20),
    }


@app.patch("/api/jobs/{job_id}")
def patch_job(job_id: str, patch: Patch):
    changes = {k: v for k, v in patch.model_dump().items() if v is not None}
    if not changes:
        raise HTTPException(400, "nothing to change")
    try:
        job = registry.update(job_id, changes)
    except KeyError:
        raise HTTPException(404, "no such job")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    scheduler.reload()
    return _decorate(job)


@app.put("/api/jobs/{job_id}/source")
def put_source(job_id: str, payload: Source):
    try:
        registry.save_source(job_id, payload.body)
    except KeyError:
        raise HTTPException(404, "no such job")
    except SyntaxError as exc:
        raise HTTPException(400, f"syntax error line {exc.lineno}: {exc.msg}")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"saved": True}


@app.post("/api/jobs/{job_id}/run")
def run_now(job_id: str, body: RunRequest | None = None, site: str | None = None):
    try:
        registry.get(job_id)
    except (KeyError, ValueError):
        raise HTTPException(404, "no such job")
    last = store.last_run(job_id)
    if last and last["status"] == "running":
        raise HTTPException(409, "this automation is already running, check Logs")
    dry = bool(body and body.dry_run)
    extra = {"site": site} if site else None
    runner.execute_async(job_id, trigger="manual", dry_run=dry, extra_args=extra)
    return {"started": True, "dry_run": dry, "site": site}


@app.post("/api/runs/{run_id}/retry")
def retry_run(run_id: int):
    """Retry = run the same job again, linked in the audit trail."""
    run = store.run(run_id)
    if not run:
        raise HTTPException(404, "no such run")
    if run["status"] == "running":
        raise HTTPException(400, "run is still in progress")
    runner.execute_async(run["job_id"], trigger=f"retry-of-{run_id}", dry_run=bool(run["dry_run"]))
    store.add_audit("dashboard", "retry", f"run:{run_id}")
    return {"started": True, "job_id": run["job_id"]}


@app.get("/api/overview")
def overview_stats(site: str | None = None):
    """Everything the stat tiles need in one call."""
    counts = {}
    try:
        for status in ("publish", "future", "draft", "pending"):
            counts[status] = len(wp_api.posts(status, 50, site=site))
    except RuntimeError:
        counts = {s: None for s in ("publish", "future", "draft", "pending")}
    today = store.now()[:10]
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()[:10]
    published = []
    try:
        published = wp_api.posts("publish", 50, site=site)
    except RuntimeError:
        pass
    return {
        **store.metrics(),
        "posts_total": sum(v for v in counts.values() if v) if any(counts.values()) else None,
        "published": counts["publish"],
        "published_today": sum(1 for p in published if (p["date_gmt"] or "").startswith(today)),
        "published_week": sum(1 for p in published if (p["date_gmt"] or "")[:10] >= week_ago),
        "scheduled": counts["future"],
        "drafts": counts["draft"],
        "pending_approval": counts["pending"],
    }


@app.post("/api/runs/{run_id}/stop")
def stop_run(run_id: int):
    if not runner.stop(run_id):
        raise HTTPException(404, "run not active")
    return {"stopped": True}


@app.get("/api/runs")
def list_runs(job: str | None = None, status: str | None = None, limit: int = 50, offset: int = 0):
    return store.runs(job_id=job, status=status, limit=min(limit, 200), offset=offset)


@app.get("/api/runs/{run_id}/logs")
def run_logs(run_id: int):
    if not store.run(run_id):
        raise HTTPException(404, "no such run")
    return store.logs(run_id)


@app.websocket("/ws/runs/{run_id}")
async def stream_logs(websocket: WebSocket, run_id: int):
    """Live tail. polling the DB beats a pubsub bus at this scale."""
    if not dash_auth.check(websocket.query_params.get("token", "")):
        await websocket.close(code=4401)
        return
    await websocket.accept()
    cursor = 0
    try:
        while True:
            for row in store.logs(run_id, after_id=cursor):
                cursor = row["id"]
                await websocket.send_json(row)
            current = store.run(run_id)
            if current and current["status"] != "running":
                await websocket.send_json({"done": True, "status": current["status"]})
                break
            await asyncio.sleep(POLL_SECONDS)
    except WebSocketDisconnect:
        pass


@app.get("/api/metrics")
def metrics():
    jobs = registry.all_jobs()
    return {
        **store.metrics(),
        "jobs_total": len(jobs),
        "jobs_enabled": sum(1 for j in jobs if j.get("enabled", True)),
        "heatmap": store.heatmap(),
    }


@app.get("/api/secrets")
def list_secrets():
    return secrets.listing()


@app.put("/api/secrets/{key}")
def set_secret(key: str, payload: SecretValue):
    try:
        secrets.set_value(key, payload.value)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    store.add_audit("dashboard", "set-secret", key, None, {"value": "***"})
    return {"saved": True}


@app.get("/api/audit")
def audit():
    return store.audit()


def _wp_guard(fn, *args, **kwargs):
    """Uniform error translation for every WP proxy call."""
    try:
        return fn(*args, **kwargs)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        raise HTTPException(502, str(exc))


@app.get("/api/wp/health")
def wp_health(site: str | None = None):
    return wp_api.health(site)


@app.get("/api/wp/posts")
def wp_posts(status: str = "publish", limit: int = 10, search: str = "",
             page: int = 1, category: int | None = None, site: str | None = None):
    return _wp_guard(wp_api.posts, status, min(limit, 50), search, max(page, 1), category, site=site)


@app.get("/api/wp/posts/{post_id}")
def wp_post_detail(post_id: int, site: str | None = None):
    return _wp_guard(wp_api.get_post, post_id, site=site)


class PostFields(BaseModel):
    title: str | None = None
    content: str | None = None
    excerpt: str | None = None
    slug: str | None = None
    status: str | None = None
    date_gmt: str | None = None
    categories: list[int] | None = None
    tags: list[int] | None = None


@app.post("/api/wp/posts")
def wp_create_post(body: PostFields, site: str | None = None):
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    fields.setdefault("status", "draft")
    result = _wp_guard(wp_api.create_post, fields, site=site)
    store.add_audit("dashboard", "post-create", f"wp:{result['id']}", None, {"title": result["title"]})
    return result


@app.patch("/api/wp/posts/{post_id}")
def wp_update_post(post_id: int, body: PostFields, site: str | None = None):
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(400, "nothing to change")
    result = _wp_guard(wp_api.update_post, post_id, fields, site=site)
    store.add_audit("dashboard", "post-update", f"wp:{post_id}", None, {"fields": list(fields)})
    return result


@app.delete("/api/wp/posts/{post_id}")
def wp_delete_post(post_id: int, force: bool = False, site: str | None = None):
    result = _wp_guard(wp_api.delete_post, post_id, force, site=site)
    store.add_audit("dashboard", "post-delete" + ("-forever" if force else ""), f"wp:{post_id}")
    return result


@app.post("/api/wp/posts/{post_id}/restore")
def wp_restore_post(post_id: int, site: str | None = None):
    result = _wp_guard(wp_api.restore_post, post_id, site=site)
    store.add_audit("dashboard", "post-restore", f"wp:{post_id}")
    return result


@app.get("/api/wp/posts/{post_id}/revisions")
def wp_revisions(post_id: int, site: str | None = None):
    return _wp_guard(wp_api.revisions, post_id, site=site)


class ImageUrl(BaseModel):
    url: str


@app.post("/api/wp/posts/{post_id}/featured")
def wp_featured(post_id: int, body: ImageUrl, site: str | None = None):
    result = _wp_guard(wp_api.set_featured_from_url, post_id, body.url, site=site)
    store.add_audit("dashboard", "post-featured-image", f"wp:{post_id}")
    return result


@app.get("/api/wp/terms")
def wp_terms(site: str | None = None):
    return _wp_guard(wp_api.terms, site=site)


class TermCreate(BaseModel):
    kind: str
    name: str


@app.post("/api/wp/terms")
def wp_create_term(body: TermCreate, site: str | None = None):
    return _wp_guard(wp_api.create_term, body.kind, body.name, site=site)


class BulkRequest(BaseModel):
    ids: list[int]
    action: str
    value: str | None = None


@app.post("/api/wp/posts/bulk")
def wp_bulk(body: BulkRequest, site: str | None = None):
    if not body.ids:
        raise HTTPException(400, "no posts selected")
    results = _wp_guard(wp_api.bulk, body.ids, body.action, body.value, site=site)
    ok = sum(1 for r in results if r["ok"])
    store.add_audit("dashboard", f"bulk-{body.action}", f"{ok}/{len(results)} posts")
    return {"results": results, "ok": ok, "failed": len(results) - ok}


class GenerateRequest(BaseModel):
    topic: str
    words: int = 800


@app.post("/api/generate")
def generate_content(body: GenerateRequest):
    """Groq research + write. Returns title/html without touching WordPress."""
    import gen

    if not body.topic.strip():
        raise HTTPException(400, "topic is required")
    try:
        title, meta, html, keywords = gen.write_full(body.topic, words=min(max(body.words, 200), 2500))
    except (RuntimeError, SystemExit) as exc:
        raise HTTPException(502, f"generation failed: {exc}")
    return {"title": title, "content": html, "excerpt": meta, "keywords": keywords}


class StatusChange(BaseModel):
    status: str


@app.post("/api/wp/posts/{post_id}/status")
def wp_set_status(post_id: int, body: StatusChange, site: str | None = None):
    result = _wp_guard(wp_api.set_status, post_id, body.status, site=site)
    store.add_audit("dashboard", f"post-{body.status}", f"wp:{post_id}")
    return result


class JobCreate(BaseModel):
    id: str
    name: str
    description: str = ""
    runtime: str = "python"
    entrypoint: str
    schedule: str = "manual"
    timeout_seconds: int = 300
    tags: list[str] = []


@app.post("/api/jobs")
def create_job(body: JobCreate):
    try:
        job = registry.create(body.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    scheduler.reload()
    return _decorate(job)


@app.post("/api/jobs/{job_id}/duplicate")
def duplicate_job(job_id: str):
    try:
        job = registry.duplicate(job_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(404 if isinstance(exc, KeyError) else 400, str(exc))
    scheduler.reload()
    return _decorate(job)


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str):
    try:
        registry.delete(job_id)
    except (KeyError, ValueError):
        raise HTTPException(404, "no such job")
    scheduler.reload()
    return {"deleted": True}


@app.get("/api/seo/audit")
def seo_audit(force: bool = False, site: str | None = None):
    from core import seo

    try:
        if force:
            return seo.audit(force=True, site=site)
        saved = seo.saved_audit(site)
        return saved if saved is not None else {"summary": None, "results": [], "generated_at": None}
    except RuntimeError as exc:
        raise HTTPException(502, str(exc))


class SeoSuggest(BaseModel):
    base: str = "posts"


@app.post("/api/seo/items/{item_id}/suggest")
def seo_suggest(item_id: int, body: SeoSuggest, site: str | None = None):
    from core import seo

    try:
        return seo.suggest_meta(body.base, item_id, site=site)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        raise HTTPException(502, str(exc))


class SeoFix(BaseModel):
    base: str = "posts"
    field: str
    value: str


@app.post("/api/seo/items/{item_id}/apply")
def seo_apply(item_id: int, body: SeoFix, site: str | None = None):
    """User approved a suggested fix — apply it to the post/page/CPT item."""
    from core import seo

    try:
        result = seo.apply_fix(body.base, item_id, body.field, body.value, site=site)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        raise HTTPException(502, str(exc))
    store.add_audit("dashboard", f"seo-fix-{body.field}", f"{body.base}:{item_id}", None, {"value": body.value[:120]})
    return result


# ── Topics ─────────────────────────────────────────────────────────────────

class TopicCreate(BaseModel):
    title: str
    category: str = ""
    site: str = ""
    status: str = "approved"


class TopicPatch(BaseModel):
    title: str | None = None
    category: str | None = None
    site: str | None = None
    status: str | None = None


@app.get("/api/topics")
def list_topics(status: str | None = None, site: str | None = None):
    from core import topics

    return {
        "suggested": topics.listing("suggested", site),
        "approved": topics.listing("approved", site),
        "written": topics.listing("written", site)[:20],
        "queue_depth": topics.queue_depth(site),
    } if status is None else topics.listing(status, site)


@app.post("/api/topics")
def create_topic(body: TopicCreate):
    from core import topics

    try:
        new_id = topics.add(body.title, source="manual", category=body.category,
                            site=body.site, status=body.status, why="added by hand")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if new_id is None:
        raise HTTPException(400, "that topic already exists")
    store.add_audit("dashboard", "topic-added", body.title[:80])
    return {"id": new_id}


@app.patch("/api/topics/{topic_id}")
def patch_topic(topic_id: int, body: TopicPatch):
    from core import topics

    changes = {k: v for k, v in body.model_dump().items() if v is not None}
    try:
        result = topics.update(topic_id, **changes)
    except KeyError:
        raise HTTPException(404, "no such topic")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if changes.get("status"):
        store.add_audit("dashboard", f"topic-{changes['status']}", result["title"][:80])
    return result


@app.post("/api/topics/{topic_id}/move")
def move_topic(topic_id: int, direction: str = "up"):
    from core import topics

    try:
        moved = topics.move(topic_id, direction)
    except KeyError:
        raise HTTPException(404, "no such topic")
    return {"moved": moved}


@app.delete("/api/topics/{topic_id}")
def delete_topic(topic_id: int):
    from core import topics

    topics.delete(topic_id)
    return {"deleted": True}


@app.post("/api/topics/discover")
def discover_topics(site: str | None = None):
    from core import topics

    try:
        created = topics.discover(site)
    except (RuntimeError, SystemExit) as exc:
        raise HTTPException(502, f"discovery failed: {exc}")
    return {"found": len(created), "topics": created}


class ImageGen(BaseModel):
    subject: str | None = None


@app.post("/api/wp/posts/{post_id}/featured/generate")
def generate_featured(post_id: int, body: ImageGen | None = None,
                      site: str | None = None):
    """AI featured image: generate, upload to WP media, attach."""
    from core import images

    subject = (body.subject if body and body.subject else None)
    if not subject:
        subject = _wp_guard(wp_api.get_post, post_id, site=site)["title"]
    try:
        media_id = images.set_featured(post_id, subject, site=site)
    except RuntimeError as exc:
        raise HTTPException(502, str(exc))
    store.add_audit("dashboard", "featured-image-generated", f"wp:{post_id}")
    return {"media_id": media_id}


@app.get("/api/notifications")
def notifications(site: str | None = None):
    """Alert center: failures + approvals + today's publishes, newest first."""
    items = [{"ts": None, "level": a["level"], "text": a["text"]} for a in alerts(site)]
    for run in store.runs(limit=15):
        if run["status"] in ("failed", "timeout"):
            items.append({"ts": run["ended_at"], "level": "error",
                          "text": f"{run['job_id']} #{run['id']} {run['status']}: {run['error']}"})
    try:
        for p in wp_api.posts("pending", 10, site=site):
            items.append({"ts": p["modified_gmt"], "level": "approval",
                          "text": f"Awaiting approval: {p['title']}"})
        today = store.now()[:10]
        for p in wp_api.posts("publish", 10, site=site):
            if (p["date_gmt"] or "").startswith(today):
                items.append({"ts": p["date_gmt"], "level": "success",
                              "text": f"Published: {p['title']}"})
    except RuntimeError:
        pass
    return items[:30]


@app.get("/api/pipeline")
def pipeline(site: str | None = None):
    """idea -> generated -> review -> approved -> scheduled -> published."""
    from core import topics as topic_engine

    queued = [t["title"] for t in topic_engine.listing("approved", site)]
    counts = {}
    for status in ("draft", "pending", "future", "publish"):
        try:
            counts[status] = wp_api.posts(status, 50, site=site)
        except RuntimeError:
            counts[status] = []
    return {
        "idea": queued,
        "generated": counts["draft"],
        "review": counts["pending"],
        "scheduled": counts["future"],
        "published": counts["publish"][:5],
        "published_total": len(counts["publish"]),
    }


@app.get("/api/alerts")
def alerts(site: str | None = None):
    """Everything that needs the user's attention, one list."""
    items = []
    health = wp_api.health(site)
    if not health["connected"]:
        items.append({"level": "critical", "text": f"WordPress connection lost: {health['error']}"})
    for run in store.runs(status="failed", limit=5):
        if run["started_at"] > store.now()[:10]:  # today only
            items.append({"level": "error", "text": f"{run['job_id']} run #{run['id']} failed: {run['error']}"})
    for run in store.runs(status="timeout", limit=3):
        items.append({"level": "error", "text": f"{run['job_id']} run #{run['id']} timed out"})
    for job in registry.all_jobs():
        if job.get("enabled", True) is False:
            items.append({"level": "warn", "text": f"job '{job['name']}' is disabled"})
    try:
        for post in wp_api.posts("future", 20, site=site):
            if post["date_gmt"] and post["date_gmt"] < store.now().replace("+00:00", ""):
                items.append({"level": "warn", "text": f"Scheduled post '{post['title']}' missed its publish time"})
        # cheap list-level SEO signal — full audit lives on the SEO page
        flagged = [p for p in wp_api.posts("publish,future,pending,draft", 50, site=site)
                   if not (p["seo"]["meta_ok"] and p["seo"]["title_ok"])]
        if flagged:
            items.append({"level": "warn", "seo": True,
                          "text": f"{len(flagged)} post(s) have SEO issues. Open the SEO page to fix them"})
    except RuntimeError:
        pass
    from core import topics as topic_engine

    depth = topic_engine.queue_depth(site)
    if depth < topic_engine.LOW_QUEUE_THRESHOLD:
        items.append({"level": "warn",
                      "text": f"Topic queue is running low ({depth} left). Approve a few suggestions when you get a chance"})
    return items


@app.get("/api/health")
def system_health(site: str | None = None):
    """Worker/scheduler/db/WP in one shot for the health strip."""
    try:
        store.metrics()
        db_ok = True
    except Exception:
        db_ok = False
    last_success = store.runs(status="success", limit=1)
    return {
        "wp": wp_api.health(site),
        "scheduler_running": scheduler._scheduler.running,
        "db_ok": db_ok,
        "workers_active": store.metrics()["running_now"] if db_ok else None,
        "last_successful_run": last_success[0]["ended_at"] if last_success else None,
    }


# Serve the built dashboard when it exists; in dev, Vite serves it on :5173 instead.
if os.path.isdir(DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(DIST, "assets")), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        # index.html must never be cached — hashed asset names handle versioning.
        return FileResponse(os.path.join(DIST, "index.html"),
                            headers={"Cache-Control": "no-cache, must-revalidate"})
