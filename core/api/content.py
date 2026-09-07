"""Business profile, change approvals, and the brief -> draft -> QA -> approve chain."""
from ninja import Router, Schema

from core import briefs, changes, profile

router = Router()


class ProfileBody(Schema):
    name: str | None = None
    description: str | None = None
    products: list[str] | None = None
    services: list[str] | None = None
    industries: list[str] | None = None
    audience: str | None = None
    locations: list[str] | None = None
    markets: list[str] | None = None
    priorities: list[dict] | None = None
    brand_voice: str | None = None
    facts: list[str] | None = None
    competitors: list[str] | None = None


class ChangePropose(Schema):
    kind: str
    wp_base: str
    wp_id: int
    after: str
    reason: str = ""


class BriefCreate(Schema):
    title: str
    topic_id: int | None = None
    instructions: str = ""


class BriefPatch(Schema):
    title: str | None = None
    primary_keyword: str | None = None
    secondary_keywords: list[str] | None = None
    intent: str | None = None
    content_type: str | None = None
    audience: str | None = None
    outline: list[dict] | None = None
    entities: list[str] | None = None
    faqs: list[str] | None = None
    internal_links: list[dict] | None = None
    cta: str | None = None
    word_target: int | None = None
    custom_instructions: str | None = None


class Approve(Schema):
    status: str = "draft"


# -- profile -------------------------------------------------------------------

@router.get("/profile")
def get_profile(request, site: str | None = None):
    return profile.get(site)


@router.put("/profile")
def save_profile(request, body: ProfileBody, site: str | None = None):
    return profile.save({k: v for k, v in body.dict().items() if v is not None}, site)


@router.post("/profile/draft")
def draft_profile(request, site: str | None = None):
    """Model reads the crawl and proposes a profile. Nothing is saved until PUT."""
    return profile.draft_from_crawl(site)


# -- changes -------------------------------------------------------------------

@router.get("/changes")
def list_changes(request, status: str | None = None, site: str | None = None):
    return changes.listing(site, status)


@router.post("/changes")
def propose_change(request, body: ChangePropose, site: str | None = None):
    return changes.propose(body.kind, body.wp_base, body.wp_id, body.after, reason=body.reason,
                           source="human", site=site)


@router.post("/changes/{change_id}/apply")
def apply_change(request, change_id: int):
    return changes.apply(change_id, actor=request.auth.username)


@router.post("/changes/{change_id}/reject")
def reject_change(request, change_id: int):
    return changes.reject(change_id, actor=request.auth.username)


@router.post("/changes/{change_id}/rollback")
def rollback_change(request, change_id: int):
    return changes.rollback(change_id, actor=request.auth.username)


# -- briefs --------------------------------------------------------------------

@router.get("/briefs")
def list_briefs(request, status: str | None = None, site: str | None = None):
    return briefs.listing(site, status)


@router.post("/briefs")
def create_brief(request, body: BriefCreate, site: str | None = None):
    return briefs.create(body.title, site=site, topic_id=body.topic_id, instructions=body.instructions)


@router.get("/briefs/{brief_id}")
def get_brief(request, brief_id: int):
    return briefs.get(brief_id)


@router.patch("/briefs/{brief_id}")
def patch_brief(request, brief_id: int, body: BriefPatch):
    return briefs.update(brief_id, **body.dict())


@router.post("/briefs/{brief_id}/draft")
def draft_brief(request, brief_id: int, site: str | None = None):
    return briefs.write_draft(brief_id, site=site)


@router.post("/briefs/{brief_id}/qa")
def qa_brief(request, brief_id: int, site: str | None = None):
    return briefs.run_qa(brief_id, site=site)


@router.post("/briefs/{brief_id}/approve")
def approve_brief(request, brief_id: int, body: Approve = None, site: str | None = None):
    return briefs.approve(brief_id, site=site, actor=request.auth.username,
                          status=body.status if body else "draft")


@router.post("/briefs/{brief_id}/reject")
def reject_brief(request, brief_id: int):
    return briefs.reject(brief_id, actor=request.auth.username)
