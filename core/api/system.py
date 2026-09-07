"""Sites, secrets, audit trail, and the aggregate dashboard endpoints."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from ninja import Router, Schema

from datetime import date, timedelta

from django.db.models import Sum

from core import costs, registry, roles, scheduler, secrets, sites, store, topics, wp_api
from core.models import Brief, Change, Crawl, GscRow, Sync
from core.api.jobs import job_for_site

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
    roles.require(request, "settings")
    result = sites.add(body.id, body.name, body.url, body.user, body.password)
    store.add_audit("dashboard", "site-added", body.id, None, {"url": body.url})
    return result


@router.post("/sites/test")
def test_site(request, body: SiteTest):
    return sites.test(body.url, body.user, body.password)


@router.delete("/sites/{site_id}")
def remove_site(request, site_id: str):
    roles.require(request, "settings")
    sites.remove(site_id)
    wp_api.invalidate()
    store.add_audit("dashboard", "site-removed", site_id)
    return {"removed": True}


@router.get("/secrets")
def list_secrets(request):
    return secrets.listing()


@router.put("/secrets/{key}")
def set_secret(request, key: str, payload: SecretValue):
    roles.require(request, "settings")
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
        "seo": seo_tiles(site),
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


CRAWL_STALE_DAYS = 14
GSC_STALE_DAYS = 4


def freshness(site):
    """Age of every dataset, so stale numbers never pass as current."""
    site_id = site or sites.default_id()
    crawl = Crawl.objects.filter(site=site_id, status="done").order_by("-id").first()
    out = {"crawl_days": (date.today() - crawl.finished_at.date()).days if crawl and crawl.finished_at else None}
    for src in ("gsc", "ga4"):
        last = Sync.objects.filter(site=site_id, source=src, error="").order_by("-id").first()
        out[f"{src}_days"] = (date.today() - last.finished_at.date()).days if last and last.finished_at else None
    return out


def seo_tiles(site):
    """Overview numbers that come from the SEO side of the house."""
    from core import seo, technical

    site_id = site or sites.default_id()
    score = None
    crawl = Crawl.objects.filter(site=site_id, status="done").order_by("-id").first()
    if crawl:
        score = technical.analyze(crawl, list(crawl.pages.all()))["score"]
    qa_done = Brief.objects.filter(site=site_id).exclude(qa={})
    passed = sum(1 for b in qa_done if (b.qa or {}).get("verdict") == "pass")
    since = date.today() - timedelta(days=31)
    clicks = GscRow.objects.filter(site=site_id, date__gte=since).aggregate(c=Sum("clicks"))["c"]
    return {"technical_score": score, "qa_pass_rate": round(passed / qa_done.count() * 100) if qa_done.count() else None,
            "pending_changes": Change.objects.filter(site=site_id, status="proposed").count(),
            "briefs_in_review": Brief.objects.filter(site=site_id, status="qa").count(),
            "gsc_clicks_28d": clicks}


def alerts_for(site):
    """Everything that needs the user's attention, one list."""
    items = []
    site_id = site or sites.default_id()
    fresh = freshness(site)
    if fresh["crawl_days"] is None:
        items.append({"level": "warn", "text": "No crawl yet - open SEO and crawl the site so the technical audit has data"})
    elif fresh["crawl_days"] > CRAWL_STALE_DAYS:
        items.append({"level": "warn", "text": f"Crawl is {fresh['crawl_days']} days old - re-crawl for a current technical audit"})
    last_gsc = Sync.objects.filter(site=site_id, source="gsc").order_by("-id").first()
    if last_gsc and last_gsc.error:
        items.append({"level": "warn", "text": f"Search Console sync: {last_gsc.error}"})
    if fresh["gsc_days"] is not None and fresh["gsc_days"] > GSC_STALE_DAYS:
        items.append({"level": "warn", "text": f"Search Console data is {fresh['gsc_days']} days old - run sync-google"})
    pending = Change.objects.filter(site=site or sites.default_id(), status="proposed").count()
    if pending:
        items.append({"level": "approval", "text": f"{pending} proposed change(s) waiting for approval on the Content page"})
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
        if job.get("enabled", True) is False and job_for_site(job, scope):
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
    import re

    seen, unique = set(), []
    for item in items:  # the alert strip and run history both report failed runs; keep one
        match = re.search(r"#(\d+)", item["text"])
        key = f"run:{match.group(1)}" if match else item["text"]
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    unique.sort(key=lambda i: i["ts"] or "￿", reverse=True)  # newest first, ts-less alerts on top
    return unique[:30]


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
        "freshness": freshness(site),
        "llm": costs.summary(),
    }
