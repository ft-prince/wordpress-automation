from ninja import Router, Schema
from ninja.errors import HttpError

from core import store, topics

router = Router()


class TopicCreate(Schema):
    title: str
    category: str = ""
    site: str = ""
    status: str = "approved"


class TopicPatch(Schema):
    title: str | None = None
    category: str | None = None
    site: str | None = None
    status: str | None = None


@router.get("/topics")
def list_topics(request, status: str | None = None, site: str | None = None):
    if status is not None:
        return topics.listing(status, site)
    return {
        "suggested": topics.listing("suggested", site),
        "approved": topics.listing("approved", site),
        "written": topics.listing("written", site)[:20],
        "queue_depth": topics.queue_depth(site),
    }


@router.post("/topics")
def create_topic(request, body: TopicCreate, site: str | None = None):
    new_id = topics.add(body.title, source="manual", category=body.category,
                        site=body.site or site or "", status=body.status, why="added by hand")
    if new_id is None:
        raise HttpError(400, "that topic already exists")
    store.add_audit("dashboard", "topic-added", body.title[:80])
    return {"id": new_id}


@router.post("/topics/discover")
def discover_topics(request, site: str | None = None):
    try:
        created = topics.discover(site)
    except (RuntimeError, SystemExit) as exc:
        raise HttpError(502, f"discovery failed: {exc}")
    return {"found": len(created), "topics": created}


@router.patch("/topics/{topic_id}")
def patch_topic(request, topic_id: int, body: TopicPatch):
    changes = {k: v for k, v in body.dict().items() if v is not None}
    result = topics.update(topic_id, **changes)
    if changes.get("status"):
        store.add_audit("dashboard", f"topic-{changes['status']}", result["title"][:80])
    return result


@router.post("/topics/{topic_id}/move")
def move_topic(request, topic_id: int, direction: str = "up"):
    return {"moved": topics.move(topic_id, direction)}


@router.delete("/topics/{topic_id}")
def delete_topic(request, topic_id: int):
    topics.delete(topic_id)
    return {"deleted": True}
