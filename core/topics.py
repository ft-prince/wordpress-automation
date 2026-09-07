"""Topic engine: discovery, approval queue, and what-to-write-next. Django ORM."""
import json
import re

from django.db import transaction
from django.db.models import Max

from core import sites, store, wp_api
from core.models import Topic

STATUSES = Topic.STATUSES
SOURCES = ("site-gap", "serp", "trending", "cluster", "manual")
LOW_QUEUE_THRESHOLD = 2


def _resolve(site):
    """Every query runs against a concrete site. No shared bucket."""
    return site or sites.default_id() or ""


def listing(status=None, site=None):
    query = Topic.objects.all()
    if status:
        query = query.filter(status=status)
    site = _resolve(site)
    if site:
        query = query.filter(site=site)
    order = ("position", "id") if status == "approved" else ("-relevance", "-id")
    return [store._row(t) for t in query.order_by(*order)[:200]]


def _next_position():
    return (Topic.objects.filter(status="approved").aggregate(m=Max("position"))["m"] or 0) + 1


def add(title, source="manual", category="", relevance=50, why="", site="", status="suggested"):
    site = _resolve(site)
    title = (title or "").strip()
    if not title:
        raise ValueError("title is required")
    if status not in STATUSES:
        raise ValueError(f"bad status: {status}")
    # Never re-suggest something already known under any status.
    if Topic.objects.filter(title__iexact=title, site=site).exists():
        return None
    return Topic.objects.create(
        title=title, source=source, category=category, relevance=int(relevance), why=why,
        site=site, status=status, position=_next_position() if status == "approved" else 0,
    ).pk


def update(topic_id, **fields):
    allowed = {"title", "category", "site", "status", "relevance", "why"}
    changes = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not changes:
        raise ValueError("nothing to change")
    if changes.get("status") not in (None, *STATUSES):
        raise ValueError(f"bad status: {changes['status']}")
    topic = Topic.objects.filter(pk=topic_id).first()
    if not topic:
        raise KeyError(topic_id)
    if changes.get("status") == "approved":
        changes["position"] = _next_position()
    for key, value in changes.items():
        setattr(topic, key, value)
    topic.save()
    return store._row(topic)


def move(topic_id, direction):
    """Swap queue position with the neighbour above/below."""
    with transaction.atomic():
        queue = list(Topic.objects.filter(status="approved").order_by("position", "id"))
        idx = next((i for i, t in enumerate(queue) if t.pk == topic_id), None)
        if idx is None:
            raise KeyError(topic_id)
        swap = idx - 1 if direction == "up" else idx + 1
        if not 0 <= swap < len(queue):
            return False
        for i, t in enumerate(queue):
            t.position = i + 1
        queue[idx].position, queue[swap].position = swap + 1, idx + 1
        Topic.objects.bulk_update(queue, ["position"])
    return True


def delete(topic_id):
    Topic.objects.filter(pk=topic_id).delete()
    return True


def next_approved(site=None):
    rows = listing(status="approved", site=site)
    return rows[0] if rows else None


def claim_next(site=None):
    """Atomically take the next queued topic so two runs can never write the same one.
    Returns the claimed topic or None. Call release() if the run fails."""
    site = _resolve(site)
    with transaction.atomic():
        topic = (Topic.objects.select_for_update().filter(status="approved", site=site)
                 .order_by("position", "id").first())
        if not topic:
            return None
        topic.status = "writing"
        topic.save(update_fields=["status"])
        return store._row(topic)


def release(topic_id):
    """A failed run puts its topic back in the queue."""
    Topic.objects.filter(pk=topic_id, status="writing").update(status="approved")


def mark_written(topic_id, post_id=None):
    Topic.objects.filter(pk=topic_id).update(status="written", post_id=post_id)


def queue_depth(site=None):
    return Topic.objects.filter(status="approved", site=_resolve(site)).count()


# -- Discovery ---------------------------------------------------------------

DISCOVER_PROMPTS = {
    "site-gap": """This company's website has these existing pages and blog posts:
{inventory}

Search the web for what companies in this exact niche publish about. Suggest {n} blog
topics this site has NOT covered yet that directly support its business. Favour topics
that connect to its product/solution pages.""",
    "serp": """Search the web for blog articles currently ranking well in this niche:
{inventory}

Suggest {n} topics where the searcher intent is clear and this company could
realistically compete. Prefer specific, long-tail angles over broad ones.""",
    "trending": """Search the web for recent news, releases and trends (last few months)
relevant to this company's field:
{inventory}

Suggest {n} timely blog topics a practitioner would genuinely want to read this month.""",
}

DISCOVER_FORMAT = """
For each topic reply with why it's worth writing and how relevant it is to THIS site.
Reply with ONLY this JSON array, nothing else:
[{{"title": "...", "category": "...", "relevance": 0-100, "why": "one concrete sentence"}}]"""


def _site_inventory(site=None):
    """Titles of everything published - the model's picture of what the site is."""
    env = sites.env_for(site)
    lines = [f"Site: {env['WEBSITE_LINK']}"]
    try:
        for p in wp_api.posts("publish", 30, site=site):
            lines.append(f"- blog post: {p['title']}")
    except RuntimeError:
        pass
    try:
        import wp

        for base in ("pages", "solution"):
            try:
                for item in wp.call(f"/{base}?per_page=30&_fields=title", env=env):
                    lines.append(f"- page: {item['title']['rendered']}")
            except RuntimeError:
                pass
    except Exception:
        pass
    return "\n".join(lines[:60])


def discover(site=None, per_source=4):
    """Run every discovery source, dedup, store as 'suggested'. Returns new topics."""
    import gen
    from concurrent.futures import ThreadPoolExecutor

    key = gen.api_key(gen.load_env())
    inventory = _site_inventory(site)

    def ask(source):
        prompt = DISCOVER_PROMPTS[source].format(inventory=inventory, n=per_source) + DISCOVER_FORMAT
        try:
            data = gen._post("/chat/completions",
                             {"model": gen.RESEARCH_MODEL,
                              "messages": [{"role": "user", "content": prompt}]}, key)
            text = data["choices"][0]["message"]["content"]
            match = re.search(r"\[.*\]", text, re.S)
            candidates = json.loads(match.group(0)) if match else []
        except (RuntimeError, json.JSONDecodeError):
            return []
        out = []
        for c in candidates[:per_source]:
            if not isinstance(c, dict) or not (c.get("title") or "").strip():
                continue
            out.append({
                "title": c["title"].strip()[:200],
                "source": source,
                "category": (c.get("category") or "").strip()[:60],
                "relevance": max(0, min(100, int(c.get("relevance") or 50))),
                "why": (c.get("why") or "").strip()[:300],
            })
        return out

    with ThreadPoolExecutor(max_workers=3) as pool:
        batches = list(pool.map(ask, DISCOVER_PROMPTS))

    created = []
    for batch in batches:
        for c in batch:
            new_id = add(site=_resolve(site), status="suggested", **c)
            if new_id:
                created.append({**c, "id": new_id})
    store.add_audit("discovery", "topics-discovered", site or "default", None, {"found": len(created)})
    return created
