"""SERP analysis without a SERP API: Groq's built-in browser_search on gpt-oss returns
the search results it used, so one call = top results for a query. Competitor pages are
then fetched with our own crawler. Cached 14 days per query."""
import re
from collections import Counter, defaultdict
from datetime import timedelta
from urllib.parse import urlsplit

from django.utils import timezone

from core import crawl, llm, profile, sites
from core.models import Cluster, SerpResult

CACHE_DAYS = 14
TOP_N = 10
FETCH_N = 5
SEARCH_MODEL = "openai/gpt-oss-120b"
SKIP_DOMAINS = ("google.", "youtube.com", "facebook.com", "linkedin.com", "twitter.com", "x.com",
                "instagram.com", "wikipedia.org", "amazon.", "reddit.com", "quora.com", "pinterest.")

ANALYSIS_PROMPT = """You are analysing the Google results for one keyword.

Keyword: {keyword}
Our site's intent guess: {intent}
Our target page (may be empty): {ours}

Top results (rank | url | title | h1 | H2 headings | words):
{serp}

Decide from the ACTUAL results, not from the keyword alone:
- dominant intent: informational | commercial | transactional | navigational
- mixed: true if results clearly serve two intents
- content_type that ranks: blog | guide | comparison | service | product | category | tool | video
- serp_patterns: what the ranking titles have in common (2-3 short phrases)
- gaps: topics/sections the top results cover that our target page lacks (skip if no target page); max 8
- competitors: the 3 domains most relevant as SEO competitors (not marketplaces or social)
- recommendation: one sentence - keep target, change target, or create a new page, and the format
Reply with ONLY this JSON:
{{"intent": "...", "mixed": false, "content_type": "...", "serp_patterns": [...], "gaps": [...],
 "competitors": [...], "recommendation": "..."}}"""


def _domain(url):
    return urlsplit(url).netloc.lower().replace("www.", "")


def search(query, country=""):
    """Top organic-ish results for a query, cached. Uses the executed tool output, which
    is the raw search result list, not the model's prose."""
    query = re.sub(r"\s+", " ", query.strip())[:200]
    cached = SerpResult.objects.filter(query__iexact=query, country=country,
                                      fetched_at__gte=timezone.now() - timedelta(days=CACHE_DAYS)).first()
    if cached:
        return cached.results
    import gen

    env = gen.load_env()
    hint = f" (searcher in {country.upper()})" if country else ""
    data = gen._post("/chat/completions", {
        "model": SEARCH_MODEL, "tools": [{"type": "browser_search"}], "reasoning_effort": "low",
        "max_completion_tokens": 3000,
        "messages": [{"role": "user", "content": f"Search the web once for exactly: {query}{hint}. Then list the top 10 result URLs."}],
    }, gen.api_key(env), purpose="serp")
    message = data["choices"][0]["message"]
    results = parse_tool_results(message.get("executed_tools") or [])
    if not results:  # fall back to URLs the model wrote
        for url in re.findall(r"https?://[^\s)\]\"']+", message.get("content") or ""):
            results.append({"url": url.rstrip(".,"), "title": "", "snippet": ""})
    results = _dedupe(results)[:TOP_N]
    SerpResult.objects.create(query=query, country=country, results=results)
    return results


def parse_tool_results(executed_tools):
    """Flatten every search the model ran into one ranked list, first search first."""
    out = []
    for tool in executed_tools:
        block = tool.get("search_results") or {}
        for r in block.get("results", []) if isinstance(block, dict) else []:
            if r.get("url"):
                out.append({"url": r["url"], "title": (r.get("title") or "")[:200], "snippet": (r.get("content") or "")[:300]})
    return out


def _dedupe(results):
    seen, out = set(), []
    for r in results:
        d = _domain(r["url"])
        if not d or any(s in d for s in SKIP_DOMAINS) or r["url"] in seen:
            continue
        seen.add(r["url"])
        out.append({**r, "domain": d})
    return out


def _fetch_summary(url):
    """Title/H1/H2s/word count of a competitor page, via the crawler's parser."""
    try:
        result = crawl.fetch(url)
    except Exception:
        return None
    if result.get("status") != 200:
        return None
    page, _ = crawl._page_from(url, result, _domain(url), 0, False, False)
    h2s = re.findall(r"<h2[^>]*>(.*?)</h2>", result["body"].decode("utf8", "replace"), flags=re.I | re.S)
    return {"title": page.title, "h1": (page.h1 or [""])[0], "words": page.word_count,
            "h2": [re.sub(r"<[^>]+>|\s+", " ", h).strip()[:80] for h in h2s[:12]]}


def analyze_cluster(cluster_id, site=None):
    """SERP for the cluster's primary keyword -> validated intent, content type, gaps."""
    cluster = Cluster.objects.filter(pk=cluster_id).first()
    if not cluster:
        raise KeyError(cluster_id)
    primary = cluster.keywords.filter(is_primary=True).first() or cluster.keywords.first()
    if not primary:
        raise ValueError("cluster has no keywords")
    env = sites.env_for(site)
    own = _domain(env["WEBSITE_LINK"])
    results = search(primary.text, (env.get("country") or "").lower()[:2])
    rows, ours = [], ""
    for rank, r in enumerate(results, 1):
        summary = _fetch_summary(r["url"]) if rank <= FETCH_N else None
        rows.append({**r, "rank": rank, "own": r["domain"] == own, **(summary or {})})
    if cluster.target_url:
        mine = _fetch_summary(cluster.target_url)
        if mine:
            ours = f"{cluster.target_url} | {mine['title']} | H2: {'; '.join(mine['h2'])} | {mine['words']} words"
    serp_lines = "\n".join(f"{r['rank']} | {r['url']} | {r.get('title', '')[:80]} | {r.get('h1', '')[:60]} | {'; '.join(r.get('h2', []))[:200]} | {r.get('words', '?')}" for r in rows)
    verdict = llm.ask_json(ANALYSIS_PROMPT.format(keyword=primary.text, intent=cluster.intent, ours=ours or "(none)", serp=serp_lines), purpose="serp")
    cluster.serp = {
        "keyword": primary.text, "fetched_at": timezone.now().isoformat(timespec="seconds"),
        "results": rows, "own_rank": next((r["rank"] for r in rows if r["own"]), None),
        "intent": verdict.get("intent") if verdict.get("intent") in ("informational", "commercial", "transactional", "navigational") else cluster.intent,
        "intent_matches": verdict.get("intent") == cluster.intent, "mixed": bool(verdict.get("mixed")),
        "content_type": verdict.get("content_type") or "", "serp_patterns": verdict.get("serp_patterns") or [],
        "gaps": [g for g in verdict.get("gaps") or [] if isinstance(g, str)][:8],
        "competitors": [c for c in verdict.get("competitors") or [] if isinstance(c, str)][:3],
        "recommendation": verdict.get("recommendation") or "",
    }
    cluster.save(update_fields=["serp"])
    return cluster.serp


def analyze_top(site=None, limit=10):
    """Analyse the highest-priority clusters that have no fresh SERP data."""
    site_id = sites.env_for(site)["_site_id"]
    cutoff = (timezone.now() - timedelta(days=CACHE_DAYS)).isoformat()
    done, errors = 0, []
    for c in Cluster.objects.filter(site=site_id).exclude(action="ignore").order_by("-priority"):
        if done >= limit:
            break
        if (c.serp or {}).get("fetched_at", "") > cutoff:
            continue
        try:
            analyze_cluster(c.pk, site)
            done += 1
        except Exception as exc:
            errors.append(f"{c.name}: {str(exc)[:120]}")
    return {"analysed": done, "errors": errors}


def competitors(site=None):
    """SEO competitors = domains that keep showing up for our keywords, ranked by how many
    clusters they appear in and how high. Business competitors are a different list."""
    env = sites.env_for(site)
    own = _domain(env["WEBSITE_LINK"])
    seen = Counter()
    best = {}
    keywords = defaultdict(list)
    pages = defaultdict(set)
    for c in Cluster.objects.filter(site=env["_site_id"]).exclude(serp={}):
        for r in c.serp.get("results", []):
            d = r.get("domain")
            if not d or d == own:
                continue
            seen[d] += 1
            best[d] = min(best.get(d, 99), r.get("rank", 99))
            keywords[d].append(c.serp.get("keyword"))
            pages[d].add(r["url"])
    return sorted([{"domain": d, "clusters": n, "best_rank": best[d], "keywords": sorted(set(keywords[d])),
                    "pages": sorted(pages[d])[:10]} for d, n in seen.items()],
                  key=lambda x: (-x["clusters"], x["best_rank"]))[:25]
