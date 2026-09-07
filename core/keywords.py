"""Keyword research -> clustering -> URL mapping -> cannibalization -> content gaps.
Free-API version: demand comes from the business profile, the crawl and the model, not a
keyword API. ponytail: LLM does the clustering; swap in embeddings when >500 keywords."""
import re
from collections import defaultdict

from django.db import transaction

from core import llm, profile, sites, store
from core.models import Brief, Cluster, Crawl, Keyword, Topic

SEED_PROMPT = """You are a keyword researcher. Start from the business, not from random keywords.

{business}

Produce the keyword universe this business should own. Reply with ONLY this JSON:
{{"seed": ["8-15 head terms buyers use for these products/services"],
 "longtail": ["20-30 specific 3-6 word phrases with clear intent"],
 "question": ["10-15 questions this audience actually asks (how/what/why/which/is)"]}}
Each keyword: lowercase, no punctuation, what a person would type into Google."""

SCORE_PROMPT = """Score each keyword for THIS business.

{business}

For every keyword give:
- intent: informational | commercial | transactional | navigational
- relevance 0-100: would ranking for it bring the right audience? (exclude popular-but-irrelevant)
- commercial 0-100: how close to a purchase/lead is this searcher for THIS business?
Keywords:
{keywords}
Reply with ONLY a JSON array in the same order: [{{"text": "...", "intent": "...", "relevance": 0, "commercial": 0}}]"""

CLUSTER_PROMPT = """Group these keywords into topic clusters. One cluster = one page that could
rank for all of its keywords. Never mix intents in a cluster (a buying keyword and a
how-to keyword are different pages). 2-12 keywords per cluster; singletons are fine.

{business}

Keywords:
{keywords}

Reply with ONLY this JSON:
[{{"name": "short cluster name", "parent_topic": "the broader pillar topic", "intent": "...",
  "role": "pillar|cluster|supporting", "primary": "the one keyword the page targets", "keywords": ["..."]}}]
Every input keyword must appear in exactly one cluster."""

MAP_PROMPT = """Decide which page on this site should rank for each keyword cluster.

{business}

Existing pages (url | title | h1 | words | type):
{pages}

Clusters:
{clusters}

For each cluster choose:
- action "existing": a listed page already fits the intent - give its url
- action "improve": a listed page is the right one but thin/misaligned - give url + what to fix
- action "new": nothing fits; only if the intent justifies a separate page
- action "ignore": not worth a page for this business
Prefer existing pages. Reply with ONLY this JSON array in the same order:
[{{"cluster": "name", "action": "...", "url": "" , "reason": "one sentence"}}]"""


def _site(site):
    return sites.env_for(site)["_site_id"]


def _norm(text):
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s-]", "", (text or "").lower())).strip()[:160]


def _row(obj, **extra):
    return {**store._row(obj), **extra}


# -- research -------------------------------------------------------------------

def _crawl_pages(site_id):
    crawl = Crawl.objects.filter(site=site_id, status="done").order_by("-id").first()
    if not crawl:
        return []
    return [p for p in crawl.pages.all() if p.indexable and p.word_count > 50]


def harvest(site=None):
    """Keywords the site already carries: titles/H1s from the crawl, topics, briefs."""
    site_id = _site(site)
    found = defaultdict(set)
    for p in _crawl_pages(site_id):
        title = re.sub(r"\s+[-|–]\s+[^-|–]+$", "", p.title)  # strip " - Brand"
        for phrase in [title] + list(p.h1):
            n = _norm(phrase)
            if 2 <= len(n.split()) <= 8:
                found[n].add(p.final_url or p.url)
    created = 0
    for text, urls in found.items():
        kw, made = Keyword.objects.get_or_create(site=site_id, text=text, defaults={"source": "crawl"})
        kw.found_on = sorted(set(kw.found_on) | urls)
        kw.save(update_fields=["found_on"])
        created += made
    for t in Topic.objects.filter(site=site_id).exclude(status="rejected"):
        _, made = Keyword.objects.get_or_create(site=site_id, text=_norm(t.title), defaults={"source": "topic"})
        created += made
    for b in Brief.objects.filter(site=site_id).exclude(primary_keyword=""):
        for text in [b.primary_keyword] + list(b.secondary_keywords):
            _, made = Keyword.objects.get_or_create(site=site_id, text=_norm(text), defaults={"source": "brief"})
            created += made
    return created


def research(site=None):
    """Seed + long-tail + questions from the business profile, then score everything unscored."""
    site_id = _site(site)
    business = profile.context(site)
    if not business:
        raise ValueError("fill in the business profile first - keyword research starts from the business")
    data = llm.ask_json(SEED_PROMPT.format(business=business))
    created = harvest(site)
    for source in ("seed", "longtail", "question"):
        for text in data.get(source, []):
            if isinstance(text, str) and _norm(text):
                _, made = Keyword.objects.get_or_create(site=site_id, text=_norm(text), defaults={"source": source})
                created += made
    scored = score(site)
    store.add_audit("ai", "keywords-researched", site_id, None, {"new": created, "scored": scored})
    return {"new": created, "scored": scored, "total": Keyword.objects.filter(site=site_id).count()}


def score(site=None, batch=40):
    """Business relevance + commercial value + intent, in batches. Only unscored rows."""
    site_id = _site(site)
    business = profile.context(site) or "(no profile)"
    pending = list(Keyword.objects.filter(site=site_id, intent=""))
    done = 0
    for i in range(0, len(pending), batch):
        chunk = pending[i:i + batch]
        try:
            rows = llm.ask_json(SCORE_PROMPT.format(business=business, keywords="\n".join(k.text for k in chunk)))
        except RuntimeError:
            continue
        by_text = {_norm(r.get("text")): r for r in rows if isinstance(r, dict)}
        for k in chunk:
            r = by_text.get(k.text)
            if not r:
                continue
            k.intent = r.get("intent") if r.get("intent") in ("informational", "commercial", "transactional", "navigational") else "informational"
            k.relevance = max(0, min(100, int(r.get("relevance") or 50)))
            k.commercial = max(0, min(100, int(r.get("commercial") or 0)))
            k.save(update_fields=["intent", "relevance", "commercial"])
            done += 1
    return done


# -- clustering -----------------------------------------------------------------

def cluster(site=None, min_relevance=30):
    """Rebuild clusters for all unclustered relevant keywords. Existing approved clusters
    keep their keywords; the model only sees what is still loose."""
    site_id = _site(site)
    loose = list(Keyword.objects.filter(site=site_id, cluster__isnull=True, relevance__gte=min_relevance))
    if not loose:
        return {"clusters": 0, "assigned": 0}
    business = profile.context(site) or "(no profile)"
    groups = llm.ask_json(CLUSTER_PROMPT.format(business=business, keywords="\n".join(f"- {k.text} [{k.intent}]" for k in loose)))
    by_text = {k.text: k for k in loose}
    made = assigned = 0
    with transaction.atomic():
        for g in groups:
            if not isinstance(g, dict) or not g.get("keywords"):
                continue
            members = [by_text[_norm(t)] for t in g["keywords"] if _norm(t) in by_text and by_text[_norm(t)].cluster_id is None]
            if not members:
                continue
            c = Cluster.objects.create(
                site=site_id, name=(g.get("name") or members[0].text)[:160],
                parent_topic=(g.get("parent_topic") or "")[:160],
                intent=g.get("intent") if g.get("intent") in ("informational", "commercial", "transactional", "navigational") else members[0].intent or "informational",
                role=g.get("role") if g.get("role") in Cluster.ROLES else "cluster")
            primary = _norm(g.get("primary"))
            for k in members:
                k.cluster, k.is_primary = c, (k.text == primary)
                k.save(update_fields=["cluster", "is_primary"])
            if not any(k.is_primary for k in members):
                best = max(members, key=lambda k: (k.relevance + k.commercial))
                best.is_primary = True
                best.save(update_fields=["is_primary"])
            c.priority = _priority(members)
            c.save(update_fields=["priority"])
            made += 1
            assigned += len(members)
    store.add_audit("ai", "keywords-clustered", site_id, None, {"clusters": made, "keywords": assigned})
    return {"clusters": made, "assigned": assigned}


def _priority(members):
    """Opportunity score, explainable: relevance and commercial value, weighted by business priorities."""
    rel = sum(k.relevance for k in members) / len(members)
    com = sum(k.commercial for k in members) / len(members)
    return round(min(100, rel * 0.5 + com * 0.4 + min(len(members), 10)))


# -- manual controls -------------------------------------------------------------

def move_keyword(keyword_id, cluster_id):
    kw = Keyword.objects.filter(pk=keyword_id).first()
    if not kw:
        raise KeyError(keyword_id)
    kw.cluster_id, kw.is_primary = cluster_id, False
    kw.save(update_fields=["cluster", "is_primary"])
    return _row(kw)


def set_primary(keyword_id):
    kw = Keyword.objects.filter(pk=keyword_id).first()
    if not kw or not kw.cluster_id:
        raise KeyError(keyword_id)
    Keyword.objects.filter(cluster_id=kw.cluster_id).update(is_primary=False)
    kw.is_primary = True
    kw.save(update_fields=["is_primary"])
    return _row(kw)


def merge(into_id, from_id):
    if into_id == from_id:
        raise ValueError("pick two different clusters")
    into, src = Cluster.objects.filter(pk=into_id).first(), Cluster.objects.filter(pk=from_id).first()
    if not (into and src):
        raise KeyError(from_id)
    Keyword.objects.filter(cluster=src).update(cluster=into, is_primary=False)
    src.delete()
    if not into.keywords.filter(is_primary=True).exists():
        best = into.keywords.order_by("-relevance", "-commercial").first()
        if best:
            best.is_primary = True
            best.save(update_fields=["is_primary"])
    return cluster_detail(into.pk)


def split(cluster_id, keyword_ids, name):
    src = Cluster.objects.filter(pk=cluster_id).first()
    if not src:
        raise KeyError(cluster_id)
    new = Cluster.objects.create(site=src.site, name=name[:160], parent_topic=src.parent_topic, intent=src.intent, role="cluster")
    moved = Keyword.objects.filter(cluster=src, pk__in=keyword_ids).update(cluster=new, is_primary=False)
    if not moved:
        new.delete()
        raise ValueError("no keywords moved")
    set_primary(new.keywords.order_by("-relevance").first().pk)
    return cluster_detail(new.pk)


def update_cluster(cluster_id, **fields):
    c = Cluster.objects.filter(pk=cluster_id).first()
    if not c:
        raise KeyError(cluster_id)
    allowed = {"name", "parent_topic", "intent", "role", "action", "target_url", "reason", "priority", "approved"}
    for key, value in fields.items():
        if key not in allowed:
            raise ValueError(f"not editable: {key}")
        if value is not None:
            setattr(c, key, value)
    if fields.get("target_url"):
        c.target_wp_base, c.target_wp_id = _wp_for(c.site, fields["target_url"])
    c.save()
    return cluster_detail(c.pk)


def delete_cluster(cluster_id):
    Keyword.objects.filter(cluster_id=cluster_id).update(cluster=None, is_primary=False)
    Cluster.objects.filter(pk=cluster_id).delete()
    return True


# -- mapping ----------------------------------------------------------------------

def _wp_for(site_id, url):
    for p in _crawl_pages(site_id):
        if (p.final_url or p.url).rstrip("/") == (url or "").rstrip("/"):
            return p.wp_base, p.wp_id
    return "", None


def map_urls(site=None, only_unmapped=True):
    """Existing page first; new page only when the intent justifies it. Suggest only -
    the SEO user approves each mapping (cluster.approved)."""
    site_id = _site(site)
    pages = _crawl_pages(site_id)
    if not pages:
        raise ValueError("crawl the site first - mapping needs the page inventory")
    clusters = Cluster.objects.filter(site=site_id).prefetch_related("keywords")
    if only_unmapped:
        clusters = clusters.filter(action="")
    clusters = list(clusters)
    if not clusters:
        return {"mapped": 0}
    page_lines = "\n".join(f"{p.final_url or p.url} | {p.title[:80]} | {(p.h1 or [''])[0][:60]} | {p.word_count} | {p.wp_base or 'template'}" for p in pages[:120])
    valid = {(p.final_url or p.url).rstrip("/") for p in pages}
    mapped = 0
    for i in range(0, len(clusters), 25):
        chunk = clusters[i:i + 25]
        lines = "\n".join(f"- {c.name} [{c.intent}]: " + ", ".join(k.text for k in c.keywords.all()) for c in chunk)
        try:
            rows = llm.ask_json(MAP_PROMPT.format(business=profile.context(site) or "(no profile)", pages=page_lines, clusters=lines))
        except RuntimeError:
            continue
        by_name = {(r.get("cluster") or "").strip().lower(): r for r in rows if isinstance(r, dict)}
        for c in chunk:
            r = by_name.get(c.name.lower())
            if not r:
                continue
            action = r.get("action") if r.get("action") in Cluster.ACTIONS else "new"
            url = (r.get("url") or "").strip()
            if action in ("existing", "improve") and url.rstrip("/") not in valid:
                action, url = "new", ""
            c.action, c.target_url, c.reason = action, url, (r.get("reason") or "")[:500]
            c.target_wp_base, c.target_wp_id = _wp_for(site_id, url) if url else ("", None)
            c.save()
            mapped += 1
    store.add_audit("ai", "clusters-mapped", site_id, None, {"mapped": mapped})
    return {"mapped": mapped}


def cannibalization(site=None):
    """Two ways pages compete: several clusters mapped to one URL with different intents,
    and several crawled pages carrying the same primary keyword in title/H1."""
    site_id = _site(site)
    issues = []
    by_url = defaultdict(list)
    for c in Cluster.objects.filter(site=site_id).exclude(target_url=""):
        by_url[c.target_url.rstrip("/")].append(c)
    for url, cs in by_url.items():
        intents = {c.intent for c in cs}
        if len(cs) > 1 and len(intents) > 1:
            issues.append({"type": "mixed-intent-target", "url": url, "clusters": [c.name for c in cs],
                           "detail": f"one page is asked to satisfy {', '.join(sorted(intents))} intents"})
    for k in Keyword.objects.filter(site=site_id, is_primary=True):
        if len(k.found_on) > 1:
            issues.append({"type": "shared-primary-keyword", "keyword": k.text, "urls": k.found_on,
                           "detail": "several pages put this keyword in their title/H1 - Google must guess which one"})
    for k in Keyword.objects.filter(site=site_id).exclude(cluster__isnull=True):
        c = k.cluster
        if c.target_url and k.found_on and c.target_url.rstrip("/") not in [u.rstrip("/") for u in k.found_on]:
            issues.append({"type": "wrong-page-targeting", "keyword": k.text, "mapped_to": c.target_url,
                           "found_on": k.found_on, "detail": "the keyword lives on a different page than the one mapped to rank for it"})
    return issues


def gaps(site=None):
    """Content plan from the mapping: missing commercial pages, pages to improve, supporting blogs."""
    site_id = _site(site)
    clusters = list(Cluster.objects.filter(site=site_id).prefetch_related("keywords").order_by("-priority"))

    def pack(c):
        return {**_row(c), "keywords": [k.text for k in c.keywords.all()],
                "primary": next((k.text for k in c.keywords.all() if k.is_primary), "")}

    new = [c for c in clusters if c.action == "new"]
    return {
        "missing_commercial_pages": [pack(c) for c in new if c.intent in ("commercial", "transactional")],
        "supporting_content": [pack(c) for c in new if c.intent in ("informational", "navigational")],
        "improve_existing": [pack(c) for c in clusters if c.action == "improve"],
        "pillars": [{"topic": t, "clusters": [pack(c) for c in cs]}
                    for t, cs in _by_parent(clusters).items()],
        "unmapped": sum(1 for c in clusters if not c.action),
    }


def _by_parent(clusters):
    out = defaultdict(list)
    for c in clusters:
        out[c.parent_topic or c.name].append(c)
    return dict(sorted(out.items(), key=lambda kv: -max(c.priority for c in kv[1])))


# -- reads ----------------------------------------------------------------------

def cluster_detail(cluster_id):
    c = Cluster.objects.filter(pk=cluster_id).first()
    if not c:
        raise KeyError(cluster_id)
    return {**_row(c), "keywords": [_row(k) for k in c.keywords.order_by("-is_primary", "-relevance")]}


def overview(site=None):
    site_id = _site(site)
    clusters = Cluster.objects.filter(site=site_id).prefetch_related("keywords").order_by("-priority", "name")
    loose = Keyword.objects.filter(site=site_id, cluster__isnull=True).order_by("-relevance")
    return {
        "counts": {"keywords": Keyword.objects.filter(site=site_id).count(), "clusters": clusters.count(),
                   "unclustered": loose.count(), "unmapped": clusters.filter(action="").count(),
                   "approved": clusters.filter(approved=True).count()},
        "clusters": [{**_row(c), "keywords": [_row(k) for k in c.keywords.order_by("-is_primary", "-relevance")]} for c in clusters],
        "unclustered": [_row(k) for k in loose[:200]],
    }


def add_keyword(text, site=None):
    site_id = _site(site)
    kw, made = Keyword.objects.get_or_create(site=site_id, text=_norm(text), defaults={"source": "manual"})
    if not made:
        raise ValueError("keyword already exists")
    return _row(kw)


def delete_keyword(keyword_id):
    Keyword.objects.filter(pk=keyword_id).delete()
    return True
