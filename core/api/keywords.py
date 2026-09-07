"""Keyword research, clusters, URL mapping, cannibalization, content gaps."""
from ninja import Router, Schema

from ninja.errors import HttpError

from core import keywords, runner, serp, sites, store

PIPELINE_JOB = "keyword-pipeline"


def _start(step, site, limit=None):
    site_id = sites.env_for(site)["_site_id"]
    last = store.runs(job_id=PIPELINE_JOB, limit=1, site=site_id)
    if last and last[0]["status"] == "running":
        raise HttpError(409, "the keyword pipeline is already running for this site - see Logs")
    extra = {"step": step, "site": site_id}
    if limit:
        extra["limit"] = limit
    runner.execute_async(PIPELINE_JOB, trigger="manual", extra_args=extra)
    return {"started": True, "job_id": PIPELINE_JOB, "step": step}

router = Router()


class KeywordAdd(Schema):
    text: str


class ClusterPatch(Schema):
    name: str | None = None
    parent_topic: str | None = None
    intent: str | None = None
    role: str | None = None
    action: str | None = None
    target_url: str | None = None
    reason: str | None = None
    priority: int | None = None
    approved: bool | None = None


class Merge(Schema):
    from_id: int


class Split(Schema):
    keyword_ids: list[int]
    name: str


class Move(Schema):
    cluster_id: int | None = None


@router.get("/keywords")
def overview(request, site: str | None = None):
    return keywords.overview(site)


@router.post("/keywords")
def add_keyword(request, body: KeywordAdd, site: str | None = None):
    return keywords.add_keyword(body.text, site)


@router.post("/keywords/research")
def research(request, site: str | None = None):
    """Starts the keyword-pipeline job (research step). Logs stream on the Logs page."""
    return _start("research", site)


@router.post("/keywords/research/sync")
def research_sync(request, site: str | None = None):
    return keywords.research(site)


@router.post("/keywords/harvest")
def harvest(request, site: str | None = None):
    return {"new": keywords.harvest(site)}


@router.post("/keywords/cluster")
def cluster(request, site: str | None = None):
    return _start("cluster", site)


@router.post("/keywords/cluster/sync")
def cluster_sync(request, site: str | None = None):
    return keywords.cluster(site)


@router.post("/keywords/map")
def map_urls(request, site: str | None = None):
    return _start("map", site)


@router.post("/keywords/map/sync")
def map_urls_sync(request, site: str | None = None, all: bool = False):
    return keywords.map_urls(site, only_unmapped=not all)


@router.get("/keywords/cannibalization")
def cannibalization(request, site: str | None = None):
    return keywords.cannibalization(site)


@router.get("/keywords/gaps")
def gaps(request, site: str | None = None):
    return keywords.gaps(site)


@router.post("/keywords/{int:keyword_id}/move")
def move_keyword(request, keyword_id: int, body: Move):
    return keywords.move_keyword(keyword_id, body.cluster_id)


@router.post("/keywords/{int:keyword_id}/primary")
def set_primary(request, keyword_id: int):
    return keywords.set_primary(keyword_id)


@router.delete("/keywords/{int:keyword_id}")
def delete_keyword(request, keyword_id: int):
    keywords.delete_keyword(keyword_id)
    return {"deleted": True}


@router.get("/clusters/{int:cluster_id}")
def cluster_detail(request, cluster_id: int):
    return keywords.cluster_detail(cluster_id)


@router.patch("/clusters/{int:cluster_id}")
def patch_cluster(request, cluster_id: int, body: ClusterPatch):
    return keywords.update_cluster(cluster_id, **body.dict())


@router.post("/clusters/{int:cluster_id}/merge")
def merge_cluster(request, cluster_id: int, body: Merge):
    return keywords.merge(cluster_id, body.from_id)


@router.post("/clusters/{int:cluster_id}/split")
def split_cluster(request, cluster_id: int, body: Split):
    return keywords.split(cluster_id, body.keyword_ids, body.name)


@router.delete("/clusters/{int:cluster_id}")
def delete_cluster(request, cluster_id: int):
    keywords.delete_cluster(cluster_id)
    return {"deleted": True}


@router.post("/clusters/{int:cluster_id}/serp")
def cluster_serp(request, cluster_id: int, site: str | None = None):
    return serp.analyze_cluster(cluster_id, site)


@router.post("/keywords/serp")
def serp_top(request, site: str | None = None, limit: int = 10):
    return _start("serp", site, limit)


@router.post("/keywords/serp/sync")
def serp_top_sync(request, site: str | None = None, limit: int = 10):
    return serp.analyze_top(site, limit)


@router.get("/keywords/pipeline")
def pipeline_status(request, site: str | None = None):
    rows = store.runs(job_id=PIPELINE_JOB, limit=1, site=sites.env_for(site)["_site_id"])
    if not rows:
        return {"run": None}
    run = rows[0]
    lines = store.logs(run["id"])
    return {"run": run, "last_line": lines[-1]["line"] if lines else ""}


@router.get("/keywords/competitors")
def competitors(request, site: str | None = None):
    return serp.competitors(site)
