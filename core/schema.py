"""JSON-LD from real page information: Article for posts, FAQPage when FAQs exist,
Organization from the business profile. Validated against required properties."""
import json
import re
from datetime import date

from core import profile, sites
from core.models import Brief

REQUIRED = {"Article": ("headline", "datePublished", "author"), "FAQPage": ("mainEntity",),
            "Organization": ("name", "url")}


def _faqs_from_html(html):
    """<h3>question</h3><p>answer</p> pairs after an FAQ heading."""
    out = []
    faq = re.split(r"<h2[^>]*>\s*(?:faq|frequently asked)[^<]*</h2>", html, flags=re.I)
    if len(faq) < 2:
        return out
    for q, a in re.findall(r"<h3[^>]*>(.*?)</h3>\s*<p>(.*?)</p>", faq[1], flags=re.I | re.S):
        out.append({"@type": "Question", "name": _text(q), "acceptedAnswer": {"@type": "Answer", "text": _text(a)}})
    return out[:10]


def _text(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html)).strip()


def for_brief(brief_id, site=None):
    brief = Brief.objects.filter(pk=brief_id).first()
    if not brief:
        raise KeyError(brief_id)
    env = sites.env_for(site)
    biz = profile.get(site)
    org = {"@type": "Organization", "name": biz["name"] or env["WEBSITE_LINK"].split("//")[-1], "url": env["WEBSITE_LINK"]}
    graph = [{
        "@type": "Article", "headline": (brief.draft_title or brief.title)[:110],
        "description": brief.draft_meta, "datePublished": date.today().isoformat(),
        "dateModified": date.today().isoformat(), "author": org, "publisher": org,
        "keywords": ", ".join([brief.primary_keyword] + brief.secondary_keywords[:5]),
        "inLanguage": env.get("language") or "en",
    }]
    faqs = _faqs_from_html(brief.draft_html)
    if faqs:
        graph.append({"@type": "FAQPage", "mainEntity": faqs})
    data = {"@context": "https://schema.org", "@graph": graph}
    errors = validate(data)
    brief.schema_jsonld = data
    brief.save(update_fields=["schema_jsonld"])
    return {"jsonld": data, "errors": errors, "types": [g["@type"] for g in graph]}


def validate(data):
    errors = []
    for node in data.get("@graph", [data]):
        for prop in REQUIRED.get(node.get("@type"), ()):
            if not node.get(prop):
                errors.append(f"{node.get('@type')}: missing {prop}")
    try:
        json.dumps(data)
    except (TypeError, ValueError) as exc:
        errors.append(f"not serialisable: {exc}")
    return errors


def script_tag(data):
    return '<script type="application/ld+json">' + json.dumps(data, ensure_ascii=False) + "</script>"


def inject(html, data):
    """Idempotent: one PressPilot JSON-LD block at the end of the content."""
    marker = "<!-- presspilot-jsonld -->"
    html = re.sub(re.escape(marker) + r".*?</script>", "", html, flags=re.S).rstrip()
    return html + "\n\n" + marker + script_tag(data)
