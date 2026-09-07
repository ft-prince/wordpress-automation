"""SEO endpoints: content audit, crawl trigger/status, technical report, on-page fixes."""
from ninja import Router, Schema
from ninja.errors import HttpError

from core import linking, roles, runner, seo, store

router = Router()
CRAWL_JOB = "crawl-site"


class SeoSuggest(Schema):
    base: str = "posts"


class SeoFix(Schema):
    base: str = "posts"
    field: str
    value: str


class OnpageApply(Schema):
    field: str
    value: str


@router.get("/seo/audit")
def seo_audit(request, force: bool = False, site: str | None = None):
    if force:
        return seo.audit(force=True, site=site)
    saved = seo.saved_audit(site)
    return saved if saved is not None else {"summary": None, "results": [], "generated_at": None}


@router.post("/seo/items/{item_id}/suggest")
def seo_suggest(request, item_id: int, body: SeoSuggest, site: str | None = None):
    return seo.suggest_meta(body.base, item_id, site=site)


@router.post("/seo/items/{item_id}/apply")
def seo_apply(request, item_id: int, body: SeoFix, site: str | None = None):
    roles.require(request, "approve")
    return seo.apply_fix(body.base, item_id, body.field, body.value, site=site, actor=request.auth.username)


@router.post("/seo/crawl")
def start_crawl(request, site: str | None = None):
    """Runs the crawl-site automation so it streams logs like every other job."""
    last = store.last_run(CRAWL_JOB)
    if last and last["status"] == "running":
        raise HttpError(409, "a crawl is already running")
    runner.execute_async(CRAWL_JOB, trigger="manual", extra_args={"site": site} if site else None)
    return {"started": True, "job_id": CRAWL_JOB}


@router.get("/seo/technical")
def technical(request, site: str | None = None):
    report = seo.technical_report(site)
    return {**report, "run": store.last_run(CRAWL_JOB)}


@router.get("/seo/pages/{page_id}")
def page_detail(request, page_id: int, site: str | None = None):
    return seo.page_detail(page_id, site=site)


@router.post("/seo/pages/{page_id}/links")
def page_links(request, page_id: int, site: str | None = None):
    return linking.plan_for_page(page_id, site=site)


@router.post("/seo/pages/{page_id}/suggest")
def onpage_suggest(request, page_id: int, site: str | None = None):
    return seo.suggest_onpage(page_id, site=site)


@router.post("/seo/pages/{page_id}/apply")
def onpage_apply(request, page_id: int, body: OnpageApply, site: str | None = None):
    roles.require(request, "approve")
    return seo.apply_onpage(page_id, body.field, body.value, site=site, actor=request.auth.username)
