"""Brief -> draft -> QA -> approve -> WordPress draft. The sheet's rule: generate from an
approved brief, never from a keyword alone, and never auto-publish."""
import re

from django.utils import timezone

from core import llm, profile, sites, store, wp_api
from core.models import Brief, Crawl, Topic

PROMPT_VERSION = "brief-v1"
META_MAX = 160

BRIEF_PROMPT = """You are an SEO strategist writing a content brief for ONE article.

{business}

Existing pages on the site the article may link to (title -> url):
{inventory}

Article topic: {title}
{instructions}
Decide the search intent (informational | commercial | transactional | navigational), the
primary keyword (2-5 words people actually type), 3-6 secondary keywords, the entities and
sub-topics a complete answer must cover, an H2/H3 outline that matches the intent, 3-5 FAQs
searchers ask, 2-4 internal links chosen ONLY from the list above, and one CTA that fits the
business. Reply with ONLY this JSON:
{{"primary_keyword": "...", "secondary_keywords": [...], "intent": "...", "content_type": "blog|guide|comparison|landing",
 "audience": "...", "entities": [...],
 "outline": [{{"h2": "...", "h3": ["..."], "notes": "what this section must say"}}],
 "faqs": ["..."], "internal_links": [{{"title": "...", "url": "..."}}],
 "cta": "...", "word_target": 900}}"""

DRAFT_PROMPT = """Write the article this brief describes. Follow the brief exactly.

{business}

BRIEF
Title: {title}
Primary keyword: {primary} (in the title, the first 100 words, and at least one <h2>)
Secondary keywords: {secondary}
Search intent: {intent} - the reader wants to {intent_hint}
Audience: {audience}
Must cover: {entities}
Outline:
{outline}
FAQs to answer (as a final <h2>FAQ</h2> section with <h3> questions): {faqs}
Internal links (use each once, as natural anchor text): {links}
CTA (last paragraph): {cta}
Length: about {words} words.
{instructions}
Voice: an experienced practitioner, direct, "you" and "we", varied sentence length, concrete
examples, positions not hedges. Banned: delve, leverage, robust, seamless, crucial, landscape,
realm, furthermore, moreover, "in today's world", "game-changer", em dashes and en dashes.
Never state a number or claim that is not in the brief or the approved facts; if you need
one, write it as a general statement instead.

Format: return ONLY raw HTML for the body (<h2>, <h3>, <p>, <ul>, <li>, <strong>, <a>). No <h1>.
First line exactly: TITLE: <the title, under 60 characters>
Second line exactly: META: <meta description, 140-155 characters>"""

QA_PROMPT = """You are a strict SEO editor reviewing a draft against its brief.

BRIEF
Primary keyword: {primary}
Intent: {intent}
Audience: {audience}
Must cover: {entities}
Approved facts: {facts}

DRAFT (HTML)
{html}

Judge:
- intent: does the draft satisfy a {intent} searcher? 0-100
- coverage: which "must cover" items are missing or shallow?
- facts: list sentences that state specific numbers, statistics, dates or named results that
  are NOT in the approved facts (these are unsupported claims)
- stuffing: is the primary keyword repeated unnaturally? true/false with an example
- readability: grade level estimate and one concrete fix
- audience: does it speak to the stated audience? one sentence
Reply with ONLY this JSON:
{{"intent_score": 0, "intent_note": "...", "missing_topics": [...], "unsupported_claims": [...],
 "stuffing": false, "stuffing_example": "", "readability_grade": 0, "readability_fix": "...",
 "audience_note": "...", "verdict": "pass|revise"}}"""

INTENT_HINT = {"informational": "learn or understand something", "commercial": "compare options before buying",
               "transactional": "take action or buy now", "navigational": "reach a specific page"}


def _row(b):
    data = store._row(b)
    data["topic"] = b.topic_id
    return data


def _inventory(site):
    """Internal-link candidates from the latest crawl, else from WordPress."""
    site_id = sites.env_for(site)["_site_id"]
    crawl = Crawl.objects.filter(site=site_id, status="done").order_by("-id").first()
    if crawl:
        pages = [p for p in crawl.pages.all() if p.status_code == 200 and p.title and p.depth <= 2]
        return [{"title": re.sub(r"\s+[-–|]\s+\S+$", "", p.title), "url": p.final_url or p.url} for p in pages[:40]]
    try:
        return [{"title": p["title"], "url": p["link"]} for p in wp_api.posts("publish", 30, site=site)]
    except RuntimeError:
        return []


def create(title, site=None, topic_id=None, instructions=""):
    """Brief from title + business profile + site inventory. Status: brief."""
    if not (title or "").strip():
        raise ValueError("title is required")
    site_id = sites.env_for(site)["_site_id"]
    inventory = _inventory(site)
    data = llm.ask_json(BRIEF_PROMPT.format(
        business=profile.context(site) or "(no business profile yet - infer from the topic)",
        inventory="\n".join(f"- {p['title']} -> {p['url']}" for p in inventory) or "(none)",
        title=title.strip(), instructions=f"Extra instructions: {instructions}" if instructions else ""))
    allowed = {p["url"] for p in inventory}
    links = [l for l in data.get("internal_links", []) if isinstance(l, dict) and l.get("url") in allowed]
    brief = Brief.objects.create(
        site=site_id, topic_id=topic_id, title=title.strip()[:200],
        primary_keyword=(data.get("primary_keyword") or "")[:120],
        secondary_keywords=[s for s in data.get("secondary_keywords", []) if isinstance(s, str)][:8],
        intent=data.get("intent") if data.get("intent") in INTENT_HINT else "informational",
        content_type=(data.get("content_type") or "blog")[:24], audience=data.get("audience") or "",
        outline=[o for o in data.get("outline", []) if isinstance(o, dict)][:12],
        entities=[e for e in data.get("entities", []) if isinstance(e, str)][:20],
        faqs=[f for f in data.get("faqs", []) if isinstance(f, str)][:6], internal_links=links[:4],
        cta=data.get("cta") or "", word_target=max(400, min(int(data.get("word_target") or 900), 2500)),
        custom_instructions=instructions, prompt_version=PROMPT_VERSION)
    store.add_audit("ai", "brief-created", brief.title[:80], None, {"brief": brief.pk})
    return _row(brief)


def update(brief_id, **fields):
    """The SEO specialist can override any part of the brief before drafting."""
    brief = Brief.objects.filter(pk=brief_id).first()
    if not brief:
        raise KeyError(brief_id)
    allowed = {"title", "primary_keyword", "secondary_keywords", "intent", "content_type", "audience",
               "outline", "entities", "faqs", "internal_links", "cta", "word_target", "custom_instructions"}
    for key, value in fields.items():
        if key not in allowed:
            raise ValueError(f"not editable: {key}")
        if value is not None:
            setattr(brief, key, value)
    brief.save()
    return _row(brief)


def write_draft(brief_id, site=None):
    """Draft strictly from the brief. Status: drafted."""
    import gen

    brief = Brief.objects.filter(pk=brief_id).first()
    if not brief:
        raise KeyError(brief_id)
    outline = "\n".join(f"- H2: {o.get('h2')}" + (f" | H3: {', '.join(o.get('h3', []))}" if o.get("h3") else "")
                        + (f" | {o.get('notes')}" if o.get("notes") else "") for o in brief.outline)
    raw = llm.ask(DRAFT_PROMPT.format(
        business=profile.context(site), title=brief.title, primary=brief.primary_keyword,
        secondary=", ".join(brief.secondary_keywords) or "none", intent=brief.intent,
        intent_hint=INTENT_HINT.get(brief.intent, "learn something"), audience=brief.audience or "general",
        entities=", ".join(brief.entities) or "as per outline", outline=outline or "- your call",
        faqs=" | ".join(brief.faqs) or "none", links=", ".join(f"{l['title']} ({l['url']})" for l in brief.internal_links) or "none",
        cta=brief.cta or "invite the reader to get in touch", words=brief.word_target,
        instructions=brief.custom_instructions), temperature=0.7)
    title, meta, html = gen._split_title(gen._strip_fences(raw))
    if not html:
        raise RuntimeError("model returned no article body")
    brief.draft_title, brief.draft_meta, brief.draft_html = title[:200], gen._cleanup(meta)[:300], gen._cleanup(html)
    brief.status, brief.qa = "drafted", {}
    brief.save()
    return _row(brief)


# -- QA ------------------------------------------------------------------------

def _text(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def deterministic_checks(brief):
    """Rules that need no model. Each: {code, ok, detail}."""
    html, text = brief.draft_html, _text(brief.draft_html)
    words = text.split()
    kw = brief.primary_keyword.lower()
    first_100 = " ".join(words[:100]).lower()
    h2s = [re.sub(r"<[^>]+>", "", h).lower() for h in re.findall(r"<h2[^>]*>(.*?)</h2>", html, re.I | re.S)]
    links = re.findall(r'href="([^"]+)"', html)
    brief_links = {l["url"] for l in brief.internal_links}
    kw_count = text.lower().count(kw) if kw else 0
    density = kw_count / max(len(words), 1) * 100
    checks = [
        ("title-has-keyword", kw in brief.draft_title.lower(), f"primary keyword in title: {brief.draft_title!r}"),
        ("title-length", 30 <= len(brief.draft_title) <= 60, f"title is {len(brief.draft_title)} chars (30-60)"),
        ("meta-length", 120 <= len(brief.draft_meta) <= META_MAX, f"meta is {len(brief.draft_meta)} chars (120-160)"),
        ("keyword-early", kw in first_100, "primary keyword within the first 100 words"),
        ("keyword-in-h2", any(kw in h for h in h2s), "primary keyword in at least one H2"),
        ("keyword-density", 0 < density <= 2.5, f"keyword density {density:.1f}% (0-2.5%)"),
        ("length", len(words) >= brief.word_target * 0.8, f"{len(words)} words vs target {brief.word_target}"),
        ("headings", len(h2s) >= 3, f"{len(h2s)} H2 headings (3+)"),
        ("internal-links", bool(brief_links & set(links)) or not brief_links, "uses the internal links from the brief"),
        ("no-h1", "<h1" not in html.lower(), "no <h1> in body"),
        ("no-dashes", not re.search(r"[–—]", html), "no em/en dashes"),
        ("outline-covered", all(any(word in text.lower() for word in (o.get("h2") or "").lower().split()[:2])
                                for o in brief.outline) if brief.outline else True, "every outline H2 topic appears"),
    ]
    return [{"code": c, "ok": bool(ok), "detail": d} for c, ok, d in checks]


def duplicate_check(brief):
    """Cheap templated-content guard: 8-word shingles shared with any crawled page."""
    crawl = Crawl.objects.filter(site=brief.site, status="done").order_by("-id").first()
    if not crawl:
        return {"ok": True, "detail": "no crawl to compare against"}
    words = _text(brief.draft_html).lower().split()
    shingles = {" ".join(words[i:i + 8]) for i in range(0, max(len(words) - 8, 0))}
    worst = (0, "")
    for p in crawl.pages.all():
        pw = p.text_sample.lower().split()
        ps = {" ".join(pw[i:i + 8]) for i in range(0, max(len(pw) - 8, 0))}
        hit = len(shingles & ps)
        if hit > worst[0]:
            worst = (hit, p.url)
    ok = worst[0] < 5
    return {"ok": ok, "detail": f"{worst[0]} shared 8-word phrases with {worst[1]}" if worst[0] else "no overlap with crawled pages"}


def run_qa(brief_id, site=None):
    """Deterministic + model checks. Status: qa. Score is explained by the individual checks."""
    brief = Brief.objects.filter(pk=brief_id).first()
    if not brief:
        raise KeyError(brief_id)
    if not brief.draft_html:
        raise ValueError("write a draft first")
    checks = deterministic_checks(brief)
    dup = duplicate_check(brief)
    facts = profile.get(site)["facts"]
    try:
        model = llm.ask_json(QA_PROMPT.format(
            primary=brief.primary_keyword, intent=brief.intent, audience=brief.audience or "general",
            entities=", ".join(brief.entities) or "n/a", facts="; ".join(map(str, facts)) or "(none approved)",
            html=brief.draft_html[:12000]))
    except RuntimeError as exc:
        model = {"error": str(exc)}
    failed = [c for c in checks if not c["ok"]]
    score = round((len(checks) - len(failed)) / len(checks) * 60 + (min(model.get("intent_score", 50), 100) / 100) * 25
                  + (10 if dup["ok"] else 0) + (5 if not model.get("unsupported_claims") else 0))
    brief.qa = {"checks": checks, "duplicate": dup, "model": model, "score": score,
                "verdict": "pass" if score >= 75 and model.get("verdict", "pass") == "pass" and not model.get("unsupported_claims") else "revise",
                "ran_at": timezone.now().isoformat(timespec="seconds")}
    brief.status = "qa"
    brief.save()
    return _row(brief)


def approve(brief_id, site=None, actor="dashboard", status="draft"):
    """Human approval creates the WordPress post as a DRAFT. Publishing stays a separate,
    explicit action in the Posts page."""
    if status not in ("draft", "pending"):
        raise ValueError("approval creates a draft or pending post, never a published one")
    brief = Brief.objects.filter(pk=brief_id).first()
    if not brief:
        raise KeyError(brief_id)
    if not brief.draft_html:
        raise ValueError("nothing to approve - write a draft first")
    post = wp_api.create_post({"title": brief.draft_title or brief.title, "content": brief.draft_html,
                               "excerpt": brief.draft_meta, "status": status}, site=site)
    brief.status, brief.post_id = "approved", post["id"]
    brief.save()
    if brief.topic_id:
        Topic.objects.filter(pk=brief.topic_id).update(status="written", post_id=post["id"])
    store.add_audit(actor, "brief-approved", brief.title[:80], None, {"post": post["id"], "qa_score": brief.qa.get("score")})
    return {**_row(brief), "post": post}


def reject(brief_id, actor="dashboard"):
    brief = Brief.objects.filter(pk=brief_id).first()
    if not brief:
        raise KeyError(brief_id)
    brief.status = "rejected"
    brief.save()
    store.add_audit(actor, "brief-rejected", brief.title[:80])
    return _row(brief)


def get(brief_id):
    brief = Brief.objects.filter(pk=brief_id).first()
    if not brief:
        raise KeyError(brief_id)
    return _row(brief)


def listing(site=None, status=None, limit=50):
    query = Brief.objects.filter(site=sites.env_for(site)["_site_id"])
    if status:
        query = query.filter(status=status)
    return [{k: v for k, v in _row(b).items() if k != "draft_html"} for b in query.order_by("-id")[:limit]]
