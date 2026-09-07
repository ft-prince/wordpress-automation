"""Internal-link suggestions with anchor text. Outbound = links the new draft should
carry; inbound = existing pages that should link to it (weak-page support). Inbound is
suggest-only: editing live page copy is a human job, proposed as a Change when asked."""
import re

from core import changes, llm, sites
from core.models import Brief, Crawl, Page

MAX_CANDIDATES = 25

PROMPT = """You are an internal-linking editor for one website.

NEW ARTICLE
Title: {title}
Primary keyword: {primary}
Summary of sections: {sections}

EXISTING PAGES (url | title | excerpt):
{pages}

1. outbound: 3-5 existing pages the new article should link TO, each with the exact
   anchor text (2-6 words, natural, appears or could appear in the article) and the
   section it belongs in.
2. inbound: 2-4 existing pages that should link TO the new article, each with one
   ready-to-paste sentence containing the anchor text, placed where it fits that page.
Only use urls from the list. Reply with ONLY this JSON:
{{"outbound": [{{"url": "...", "anchor": "...", "section": "...", "reason": "..."}}],
 "inbound": [{{"url": "...", "anchor": "...", "sentence": "...", "reason": "..."}}]}}"""


def _candidates(site_id, exclude_url=""):
    crawl = Crawl.objects.filter(site=site_id, status="done").order_by("-id").first()
    if not crawl:
        return []
    pages = [p for p in crawl.pages.all() if p.indexable and p.word_count > 80 and (p.final_url or p.url) != exclude_url]
    pages.sort(key=lambda p: (p.depth, -p.word_count))
    return pages[:MAX_CANDIDATES]


def _ask(title, primary, sections, pages):
    if not pages:
        raise ValueError("crawl the site first - link suggestions need the page inventory")
    lines = "\n".join(f"{p.final_url or p.url} | {p.title[:70]} | {p.text_sample[:160]}" for p in pages)
    data = llm.ask_json(PROMPT.format(title=title, primary=primary, sections=sections, pages=lines), purpose="linking")
    valid = {(p.final_url or p.url) for p in pages}
    clean = lambda rows, keys: [{k: str(r.get(k, ""))[:300] for k in keys} for r in rows
                                if isinstance(r, dict) and r.get("url") in valid and r.get("anchor")]
    return {"outbound": clean(data.get("outbound", []), ("url", "anchor", "section", "reason"))[:5],
            "inbound": clean(data.get("inbound", []), ("url", "anchor", "sentence", "reason"))[:4]}


def plan_for_brief(brief_id, site=None):
    brief = Brief.objects.filter(pk=brief_id).first()
    if not brief:
        raise KeyError(brief_id)
    sections = "; ".join(o.get("h2", "") for o in brief.outline) or brief.title
    plan = _ask(brief.draft_title or brief.title, brief.primary_keyword, sections, _candidates(brief.site))
    brief.link_plan = plan
    brief.save(update_fields=["link_plan"])
    return plan


def apply_outbound(brief_id):
    """Turn each outbound suggestion into a real <a> in the draft: first plain occurrence
    of the anchor text, else appended to the named section's first paragraph."""
    brief = Brief.objects.filter(pk=brief_id).first()
    if not brief:
        raise KeyError(brief_id)
    html, done = brief.draft_html, []
    for link in brief.link_plan.get("outbound", []):
        if link["url"] in html:
            continue
        anchor = re.escape(link["anchor"])
        pattern = re.compile(rf"(?<![>\w])({anchor})(?![\w<])", re.I)
        new_html, n = pattern.subn(rf'<a href="{link["url"]}">\1</a>', html, count=1)
        if n == 0:
            new_html = re.sub(r"(</p>)", rf' See <a href="{link["url"]}">{link["anchor"]}</a>.\1', html, count=1)
        html = new_html
        done.append(link["url"])
    brief.draft_html = html
    brief.save(update_fields=["draft_html"])
    return {"linked": done}


def plan_for_page(page_id, site=None):
    """Weak-page support: which existing pages should link to this crawled page."""
    page = Page.objects.filter(pk=page_id).first()
    if not page:
        raise KeyError(page_id)
    plan = _ask(page.title or page.url, (page.h1 or [page.title or ""])[0], page.text_sample[:300],
                _candidates(page.crawl.site, page.final_url or page.url))
    return {"inbound": plan["inbound"], "outbound": plan["outbound"]}


def propose_inbound(source_wp_base, source_wp_id, sentence, site=None):
    """Append the suggested sentence as a new paragraph at the end of the source page,
    through the change gate so a human approves it and it can be rolled back."""
    from core import wp_api

    item = wp_api.get_item(source_wp_base, source_wp_id, site=site)
    before = item["content_raw"]
    if not before.strip():
        raise ValueError("that page is template-driven; add the link in the theme instead")
    after = before.rstrip() + f"\n\n<p>{sentence}</p>"
    return changes.propose("content", source_wp_base, source_wp_id, after, before=before,
                           reason="internal link to new content", source="ai", site=site)
