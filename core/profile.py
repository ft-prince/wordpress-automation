"""Business profile per site: stored by hand, optionally drafted by the model from the
crawl. Everything content-related reads `context()` for its prompt."""
from core import llm, sites
from core.models import BusinessProfile, Crawl

FIELDS = ("name", "description", "products", "services", "industries", "audience", "locations",
          "markets", "priorities", "brand_voice", "facts", "competitors")
LIST_FIELDS = {"products", "services", "industries", "locations", "markets", "priorities", "facts", "competitors"}


def get(site=None):
    site_id = sites.env_for(site)["_site_id"]
    row, _ = BusinessProfile.objects.get_or_create(site=site_id)
    return {f: getattr(row, f) for f in FIELDS} | {"site": site_id, "updated_at": row.updated_at.isoformat(timespec="seconds"),
                                                   "is_empty": not (row.description or row.products or row.services)}


def save(fields, site=None):
    site_id = sites.env_for(site)["_site_id"]
    row, _ = BusinessProfile.objects.get_or_create(site=site_id)
    for key, value in fields.items():
        if key not in FIELDS:
            raise ValueError(f"unknown profile field: {key}")
        if key in LIST_FIELDS and not isinstance(value, list):
            raise ValueError(f"{key} must be a list")
        setattr(row, key, value)
    row.save()
    return get(site)


DRAFT_PROMPT = """Read these pages from a company website and describe the business.

{pages}

Reply with ONLY this JSON object (lists of short strings, be specific, no marketing fluff):
{{"name": "...", "description": "two sentences on what the company does",
 "products": [...], "services": [...], "industries": [...],
 "audience": "who buys this, in one or two sentences",
 "locations": [...], "markets": [...],
 "brand_voice": "one sentence describing the tone of the site copy",
 "facts": ["verifiable claims stated on the site, with numbers where present"],
 "competitors": []}}"""


def draft_from_crawl(site=None):
    """First fill: let the model read the crawled pages. The user edits, then saves."""
    site_id = sites.env_for(site)["_site_id"]
    crawl = Crawl.objects.filter(site=site_id, status="done").order_by("-id").first()
    if not crawl:
        raise ValueError("crawl the site first - the profile draft reads the crawled pages")
    pages = [p for p in crawl.pages.all() if p.status_code == 200 and p.word_count > 80 and p.wp_base != "posts"]
    pages.sort(key=lambda p: p.depth)
    blob = "\n\n".join(f"URL: {p.url}\nTITLE: {p.title}\n{p.text_sample[:1200]}" for p in pages[:12])
    data = llm.ask_json(DRAFT_PROMPT.format(pages=blob))
    return {k: data.get(k, [] if k in LIST_FIELDS else "") for k in FIELDS if k != "priorities"} | {"priorities": []}


def context(site=None):
    """Compact prompt block. Empty profile -> empty string, so prompts still work."""
    p = get(site)
    if p["is_empty"]:
        return ""
    lines = [f"Business: {p['name'] or p['site']}. {p['description']}"]
    for key in ("products", "services", "industries", "locations", "markets"):
        if p[key]:
            lines.append(f"{key.capitalize()}: {', '.join(map(str, p[key]))}")
    if p["audience"]:
        lines.append(f"Audience: {p['audience']}")
    if p["priorities"]:
        lines.append("Priorities: " + ", ".join(f"{x.get('topic')} (weight {x.get('weight', 3)})" for x in p["priorities"] if isinstance(x, dict)))
    if p["brand_voice"]:
        lines.append(f"Brand voice: {p['brand_voice']}")
    if p["facts"]:
        lines.append("Approved facts (only these may be stated as fact):\n- " + "\n- ".join(map(str, p["facts"])))
    return "\n".join(lines)
