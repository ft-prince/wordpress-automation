"""Sites, secrets, audit trail, and the aggregate dashboard endpoints."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from ninja import Router, Schema

from core import registry, scheduler, secrets, sites, store, topics, wp_api
from core.api.jobs import job_site

router = Router()


class SiteCreate(Schema):
    id: str
    name: str
    url: str
    user: str
    password: str


class SiteTest(Schema):
    url: str
    user: str
    password: str


class SecretValue(Schema):
    value: str


@router.get("/sites")
def list_sites(request):
    return {"sites": sites.all_sites(), "default": sites.default_id()}


@router.post("/sites")
def add_site(request, body: SiteCreate):
    result = sites.add(body.id, body.name, body.url, body.user, body.password)
    store.add_audit("dashboard", "site-added", body.id, None, {"url": body.url})
    return result


@router.post("/sites/test")
def test_site(request, body: SiteTest):
    return sites.test(body.url, body.user, body.password)


@router.delete("/sites/{site_id}")
def remove_site(request, site_id: str):
    sites.remove(site_id)
    wp_api.invalidate()
    store.add_audit("dashboard", "site-removed", site_id)
    return {"removed": True}


@router.get("/secrets")
def list_secrets(request):
    return secrets.listing()


@router.put("/secrets/{key}")
def set_secret(request, key: str, payload: SecretValue):
    secrets.set_value(key, payload.value)
    store.add_audit("dashboard", "set-secret", key, None, {"value": "***"})
    return {"saved": True}


@router.get("/audit")
def audit(request):
    return store.audit()


def posts_by_status(statuses, site, limit=50):
    """Fetch several status lists concurrently. A status that errors comes back as
    None so callers can tell 'empty' from 'unreachable'."""
    def one(status):
        try:
            return wp_api.posts(status, limit, site=site)
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=len(statuses)) as pool:
        return dict(zip(statuses, pool.map(one, statuses)))


@router.get("/overview")
def overview_stats(request, site: str | None = None):
    """Everything the stat tiles need in one call."""
    lists = posts_by_status(("publish", "future", "draft", "pending"), site)
    counts = {s: (len(v) if v is not None else None) for s, v in lists.items()}
    today = store.now()[:10]
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()[:10]
    published = lists["publish"] or []
    return {
        **store.metrics(site=site or sites.default_id()),
        "posts_total": None if all(v is None for v in counts.values())
        else sum(v or 0 for v in counts.values()),
        "published": counts["publish"],
        "published_today": sum(1 for p in published if (p["date_gmt"] or "").startswith(today)),
        "published_week": sum(1 for p in published if (p["date_gmt"] or "")[:10] >= week_ago),
        "scheduled": counts["future"],
        "drafts": counts["draft"],
        "pending_approval": counts["pending"],
    }


@router.get("/pipeline")
def pipeline(request, site: str | None = None):
    """idea -> generated -> review -> approved -> scheduled -> published."""
    queued = [t["title"] for t in topics.listing("approved", site)]
    lists = posts_by_status(("draft", "pending", "future", "publish"), site)
    counts = {s: (v or []) for s, v in lists.items()}
    return {
        "idea": queued,
        "generated": counts["draft"],
        "review": counts["pending"],
        "scheduled": counts["future"],
        "published": counts["publish"][:5],
        "published_total": len(counts["publish"]),
    }


def alerts_for(site):
    """Everything that needs the user's attention, one list."""
    items = []
    health = wp_api.health(site)
    if not health["connected"]:
        items.append({"level": "critical", "text": f"WordPress connection lost: {health['error']}"})
    scope = site or sites.default_id()
    for run in store.runs(status="failed", limit=5, site=scope):
        if run["started_at"] > store.now()[:10]:  # today only
            items.append({"level": "error", "text": f"{run['job_id']} run #{run['id']} failed: {run['error']}"})
    for run in store.runs(status="timeout", limit=3, site=scope):
        items.append({"level": "error", "text": f"{run['job_id']} run #{run['id']} timed out"})
    for job in registry.all_jobs():
        if job.get("enabled", True) is False and job_site(job) == scope:
            items.append({"level": "warn", "text": f"job '{job['name']}' is disabled"})
    try:
        for post in wp_api.posts("future", 20, site=site):
            if post["date_gmt"] and post["date_gmt"] < store.now().replace("+00:00", ""):
                items.append({"level": "warn", "text": f"Scheduled post '{post['title']}' missed its publish time"})
        flagged = [p for p in wp_api.posts("publish,future,pending,draft", 50, site=site)
                   if not (p["seo"]["meta_ok"] and p["seo"]["title_ok"])]
        if flagged:
            items.append({"level": "warn", "seo": True,
                          "text": f"{len(flagged)} post(s) have SEO issues. Open the SEO page to fix them"})
    except RuntimeError:
        pass
    depth = topics.queue_depth(site)
    if depth < topics.LOW_QUEUE_THRESHOLD:
        items.append({"level": "warn",
                      "text": f"Topic queue is running low ({depth} left). Approve a few suggestions when you get a chance"})
    return items


@router.get("/alerts")
def alerts(request, site: str | None = None):
    return alerts_for(site)


@router.get("/notifications")
def notifications(request, site: str | None = None):
    """Alert center: failures + approvals + today's publishes, newest first."""
    items = [{"ts": None, "level": a["level"], "text": a["text"]} for a in alerts_for(site)]
    for run in store.runs(limit=15, site=site or sites.default_id()):
        if run["status"] in ("failed", "timeout"):
            items.append({"ts": run["ended_at"], "level": "error",
                          "text": f"{run['job_id']} #{run['id']} {run['status']}: {run['error']}"})
    try:
        # limit 50 on purpose: shares the cache entry overview/pipeline already keep warm
        for p in wp_api.posts("pending", 50, site=site)[:10]:
            items.append({"ts": p["modified_gmt"], "level": "approval",
                          "text": f"Awaiting approval: {p['title']}"})
        today = store.now()[:10]
        for p in wp_api.posts("publish", 50, site=site)[:10]:
            if (p["date_gmt"] or "").startswith(today):
                items.append({"ts": p["date_gmt"], "level": "success",
                              "text": f"Published: {p['title']}"})
    except RuntimeError:
        pass
    items.sort(key=lambda i: i["ts"] or "￿", reverse=True)  # newest first, ts-less alerts on top
    return items[:30]


@router.get("/health")
def system_health(request, site: str | None = None):
    """Worker/scheduler/db/WP in one shot for the health strip."""
    try:
        running_now = store.metrics()["running_now"]
        db_ok = True
    except Exception:
        running_now, db_ok = None, False
    last_success = store.runs(status="success", limit=1, site=site or sites.default_id())
    return {
        "wp": wp_api.health(site),
        "scheduler_running": scheduler._scheduler.running,
        "db_ok": db_ok,
        "workers_active": running_now,
        "last_successful_run": last_success[0]["ended_at"] if last_success else None,
    }
