"""Approval gate. propose() records what would change; apply() is the only path that
writes SEO edits to WordPress; rollback() writes `before` back. The CRUD sheet says:
must log = always, rollback = always, no blind auto-apply."""
from django.utils import timezone

from core import sites, store, wp_api
from core.models import Change

# Which WordPress item field each change kind lands on.
FIELD_FOR = {"title": "title", "h1": "title", "meta": "meta_desc", "content": "content",
             "slug": "slug", "excerpt": "excerpt"}


def _row(change):
    return store._row(change)


def _current(base, item_id, field, site):
    item = wp_api.get_item(base, item_id, site=site)
    if field == "meta_desc" and item["supports_excerpt"]:
        field = "excerpt"
    key = {"title": "title", "excerpt": "excerpt_raw", "meta_desc": "meta_desc",
           "content": "content_raw", "slug": "slug"}[field]
    return field, item.get(key)


def propose(kind, wp_base, wp_id, after, reason="", source="ai", site=None, before=None):
    """Record a candidate change. `before` is read live from WordPress unless given."""
    if kind not in FIELD_FOR:
        raise ValueError(f"unknown change kind: {kind}")
    env = sites.env_for(site)
    field = FIELD_FOR[kind]
    if before is None:
        field, before = _current(wp_base, wp_id, field, site)
    if before == after:
        raise ValueError("nothing would change")
    change = Change.objects.create(site=env["_site_id"], kind=kind, wp_base=wp_base, wp_id=wp_id,
                                   field=field, before=before, after=after, reason=reason, source=source)
    store.add_audit(source, f"proposed-{kind}", f"{wp_base}:{wp_id}", None, {"change": change.pk})
    return _row(change)


def apply(change_id, actor="dashboard"):
    """Human said yes: write `after` to WordPress, keep `before` for rollback."""
    change = Change.objects.filter(pk=change_id).first()
    if not change:
        raise KeyError(change_id)
    if change.status != "proposed":
        raise ValueError(f"change is {change.status}, not proposed")
    try:
        wp_api.update_item(change.wp_base, change.wp_id, {change.field: change.after}, site=change.site)
    except (RuntimeError, ValueError) as exc:
        change.status, change.error = "failed", str(exc)[:500]
        change.save()
        raise
    change.status, change.decided_at, change.decided_by = "applied", timezone.now(), actor
    change.save()
    store.add_audit(actor, f"applied-{change.kind}", f"{change.wp_base}:{change.wp_id}",
                    {change.field: change.before}, {change.field: change.after})
    return _row(change)


def reject(change_id, actor="dashboard"):
    change = Change.objects.filter(pk=change_id, status="proposed").first()
    if not change:
        raise KeyError(change_id)
    change.status, change.decided_at, change.decided_by = "rejected", timezone.now(), actor
    change.save()
    return _row(change)


def rollback(change_id, actor="dashboard"):
    """Write the stored `before` value back. Only applied changes can be rolled back."""
    change = Change.objects.filter(pk=change_id).first()
    if not change:
        raise KeyError(change_id)
    if change.status != "applied":
        raise ValueError(f"change is {change.status}, only applied changes roll back")
    wp_api.update_item(change.wp_base, change.wp_id, {change.field: change.before or ""}, site=change.site)
    change.status, change.decided_at, change.decided_by = "rolled_back", timezone.now(), actor
    change.save()
    store.add_audit(actor, f"rolled-back-{change.kind}", f"{change.wp_base}:{change.wp_id}",
                    {change.field: change.after}, {change.field: change.before})
    return _row(change)


def listing(site=None, status=None, limit=100):
    query = Change.objects.filter(site=sites.env_for(site)["_site_id"])
    if status:
        query = query.filter(status=status)
    return [_row(c) for c in query.order_by("-id")[:limit]]


def propose_and_apply(kind, wp_base, wp_id, after, reason="", source="human", site=None, actor="dashboard"):
    """The one-click path the dashboard already uses: the user IS the approval."""
    change = propose(kind, wp_base, wp_id, after, reason=reason, source=source, site=site)
    return apply(change["id"], actor=actor)
