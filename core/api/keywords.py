"""Keyword research, clusters, URL mapping, cannibalization, content gaps."""
from ninja import Router, Schema

from core import keywords

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
    return keywords.research(site)


@router.post("/keywords/harvest")
def harvest(request, site: str | None = None):
    return {"new": keywords.harvest(site)}


@router.post("/keywords/cluster")
def cluster(request, site: str | None = None):
    return keywords.cluster(site)


@router.post("/keywords/map")
def map_urls(request, site: str | None = None, all: bool = False):
    return keywords.map_urls(site, only_unmapped=not all)


@router.get("/keywords/cannibalization")
def cannibalization(request, site: str | None = None):
    return keywords.cannibalization(site)


@router.get("/keywords/gaps")
def gaps(request, site: str | None = None):
    return keywords.gaps(site)


@router.post("/keywords/{keyword_id}/move")
def move_keyword(request, keyword_id: int, body: Move):
    return keywords.move_keyword(keyword_id, body.cluster_id)


@router.post("/keywords/{keyword_id}/primary")
def set_primary(request, keyword_id: int):
    return keywords.set_primary(keyword_id)


@router.delete("/keywords/{keyword_id}")
def delete_keyword(request, keyword_id: int):
    keywords.delete_keyword(keyword_id)
    return {"deleted": True}


@router.get("/clusters/{cluster_id}")
def cluster_detail(request, cluster_id: int):
    return keywords.cluster_detail(cluster_id)


@router.patch("/clusters/{cluster_id}")
def patch_cluster(request, cluster_id: int, body: ClusterPatch):
    return keywords.update_cluster(cluster_id, **body.dict())


@router.post("/clusters/{cluster_id}/merge")
def merge_cluster(request, cluster_id: int, body: Merge):
    return keywords.merge(cluster_id, body.from_id)


@router.post("/clusters/{cluster_id}/split")
def split_cluster(request, cluster_id: int, body: Split):
    return keywords.split(cluster_id, body.keyword_ids, body.name)


@router.delete("/clusters/{cluster_id}")
def delete_cluster(request, cluster_id: int):
    keywords.delete_cluster(cluster_id)
    return {"deleted": True}
