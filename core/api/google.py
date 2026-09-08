"""Google OAuth connection, GSC/GA4 sync, and the performance insights."""
from django.http import HttpResponseRedirect
from ninja import Router, Schema

from core import google, insights, keywords, runner, sites, store

router = Router()
SYNC_JOB = "sync-google"


class SiteSettings(Schema):
    gsc_property: str | None = None
    ga4_property: str | None = None
    country: str | None = None
    language: str | None = None


def _base(request):
    """Must equal the redirect URI registered in Google Cloud. PUBLIC_URL wins when set
    (tunnel / reverse proxy); locally the loopback address is what was registered."""
    from django.conf import settings

    if settings.PUBLIC_URL:
        return settings.PUBLIC_URL
    host = request.get_host().replace("localhost", "127.0.0.1")
    return f"{request.scheme}://{host}"


@router.get("/google/status")
def status(request, site: str | None = None):
    return google.status(site)


@router.get("/google/auth-url")
def auth_url(request):
    return {"url": google.auth_url(_base(request))}


@router.get("/google/callback", auth=None)
def callback(request, code: str = "", state: str = "", error: str = ""):
    """Google lands here. Public by necessity; the state token is the guard."""
    if error or not code:
        return HttpResponseRedirect(f"/sites?google=error&reason={error or 'no-code'}")
    google.exchange_code(code, state, _base(request))
    store.add_audit("dashboard", "google-connected", "oauth")
    return HttpResponseRedirect("/sites?google=connected")


@router.post("/google/disconnect")
def disconnect(request):
    google.disconnect()
    store.add_audit("dashboard", "google-disconnected", "oauth")
    return {"ok": True}


@router.get("/google/properties")
def properties(request):
    return google.list_properties()


@router.patch("/sites/{site_id}/settings")
def site_settings(request, site_id: str, body: SiteSettings):
    return sites.update(site_id, **{k: v for k, v in body.dict().items() if v is not None})


@router.post("/google/sync")
def sync(request, site: str | None = None):
    """Runs the sync-google automation so it logs like every other job."""
    last = store.last_run(SYNC_JOB)
    if last and last["status"] == "running":
        return {"started": False, "detail": "sync already running"}
    runner.execute_async(SYNC_JOB, trigger="manual", extra_args={"site": site} if site else None)
    return {"started": True, "job_id": SYNC_JOB}


@router.get("/insights")
def all_insights(request, site: str | None = None):
    return {
        "report": insights.traffic_report(site),
        "page1": insights.page1_opportunities(site),
        "ctr": insights.ctr_opportunities(site),
        "cannibalization": insights.cannibalization(site),
        "new_keywords": insights.new_keywords(site),
        "ranking_decline": insights.ranking_decline(site),
        "traffic_decline": insights.traffic_decline(site),
        "refresh_plan": insights.refresh_plan(site),
    }


@router.post("/insights/adopt-keywords")
def adopt_keywords(request, site: str | None = None, limit: int = 50):
    """Pull the top unknown GSC queries into the keyword database (source gsc)."""
    added = 0
    for r in insights.new_keywords(site, limit):
        try:
            kw = keywords.add_keyword(r["query"], site)
            from core.models import Keyword

            Keyword.objects.filter(pk=kw["id"]).update(source="gsc", found_on=[r["page"]])
            added += 1
        except ValueError:
            pass
    return {"added": added}
