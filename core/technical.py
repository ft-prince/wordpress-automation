"""Technical + on-page checks over one crawl. Pure functions on Page rows; no network.
Every issue names the rule, the severity and the URLs so the score is explainable."""
import re
from collections import Counter, defaultdict
from urllib.parse import urlsplit

from core.crawl import normalize

TITLE_MIN, TITLE_MAX = 30, 60
META_MIN, META_MAX = 70, 160
THIN_WORDS = 150
SLOW_MS = 1500
HEAVY_BYTES = 1_500_000
URL_MAX = 100
DEEP_SEGMENTS = 4
DEEP_CLICKS = 4
LOW_INBOUND = 2
WEIGHT = {"high": 15, "medium": 7, "low": 3}
MAX_HOPS = 6

# code -> (category, severity, label, detail)
RULES = {
    "http-5xx": ("status", "high", "Server error", "Page returns a 5xx - it cannot be crawled or indexed."),
    "http-4xx": ("status", "high", "Page not found", "Page returns a 4xx. Redirect it or fix the links pointing here."),
    "fetch-error": ("status", "high", "Could not fetch", "Timeout, TLS or DNS failure while fetching."),
    "broken-internal-link": ("links", "high", "Broken internal link", "Links to a URL on this site that returns 4xx/5xx."),
    "redirected-internal-link": ("links", "low", "Internal link to a redirect", "Link straight to the final URL to save a hop."),
    "broken-external-link": ("links", "medium", "Broken external link", "Links to an external URL that no longer resolves."),
    "redirect-chain": ("redirects", "medium", "Redirect chain", "More than one hop before the final page."),
    "redirect-loop": ("redirects", "high", "Redirect loop", "Redirects never settle on a page."),
    "noindex": ("indexability", "medium", "Marked noindex", "This page asks search engines not to index it."),
    "robots-blocked": ("indexability", "high", "Blocked by robots.txt", "In the sitemap but disallowed for crawlers."),
    "canonical-missing": ("canonical", "medium", "Canonical missing", "No rel=canonical - duplicates can split ranking signals."),
    "canonical-other": ("canonical", "low", "Canonical points elsewhere", "Search engines will credit the canonical target, not this URL."),
    "canonical-broken": ("canonical", "high", "Canonical target not indexable", "The canonical URL is missing, redirected or noindex."),
    "sitemap-missing": ("sitemap", "medium", "No XML sitemap", "None of the usual sitemap locations answered."),
    "sitemap-url-broken": ("sitemap", "high", "Sitemap lists a broken URL", "Sitemap URL returns non-200 or redirects."),
    "sitemap-url-noindex": ("sitemap", "medium", "Sitemap lists a noindex page", "Contradictory signals confuse crawlers."),
    "not-in-sitemap": ("sitemap", "low", "Indexable page missing from sitemap", "Add it so it is discovered and refreshed promptly."),
    "duplicate-title": ("duplicates", "medium", "Duplicate title", "Several pages share the same <title>."),
    "duplicate-meta": ("duplicates", "low", "Duplicate meta description", "Several pages share the same description."),
    "duplicate-h1": ("duplicates", "low", "Duplicate H1", "Several pages share the same H1."),
    "duplicate-content": ("duplicates", "high", "Duplicate content", "Body text is identical to another page."),
    "duplicate-url": ("duplicates", "medium", "URL variants both live", "Same page reachable at more than one URL (slash, case, query)."),
    "url-uppercase": ("url", "low", "Uppercase in URL", "Lowercase URLs avoid case-duplicates."),
    "url-underscore": ("url", "low", "Underscores in URL", "Use hyphens - Google treats underscores as joiners."),
    "url-long": ("url", "low", "Very long URL", f"Over {URL_MAX} characters."),
    "url-query": ("url", "low", "Query string URL", "Parameter URLs often duplicate a clean one."),
    "url-deep": ("url", "low", "Deep URL path", f"More than {DEEP_SEGMENTS} path segments."),
    "h1-missing": ("headings", "high", "H1 missing", "Every page needs one H1 naming its topic."),
    "h1-multiple": ("headings", "medium", "Multiple H1s", "One H1 per page keeps the topic unambiguous."),
    "h2-missing": ("headings", "low", "No H2 subheadings", "Long pages without H2s read as walls of text."),
    "title-missing": ("titles", "high", "Title missing", "No <title> - Google will invent one."),
    "title-long": ("titles", "medium", "Title too long", f"Over {TITLE_MAX} characters gets cut in results."),
    "title-short": ("titles", "low", "Title too short", f"Under {TITLE_MIN} characters wastes the snippet."),
    "meta-missing": ("meta", "medium", "Meta description missing", "Google picks its own snippet without one."),
    "meta-long": ("meta", "low", "Meta description too long", f"Over {META_MAX} characters gets truncated."),
    "meta-short": ("meta", "low", "Meta description short", f"Under {META_MIN} characters under-sells the page."),
    "orphan": ("links", "high", "Orphan page", "No other page links here - crawlers may never find it."),
    "low-inbound": ("links", "low", "Few internal links in", f"Fewer than {LOW_INBOUND} internal links pointing here."),
    "deep-click": ("links", "medium", "Deep in the site", f"{DEEP_CLICKS}+ clicks from the homepage."),
    "no-outbound-internal": ("links", "low", "No internal links out", "Dead-end pages waste crawl equity."),
    "img-missing-alt": ("images", "low", "Images without alt text", "Alt text is accessibility and image-search relevance."),
    "page-slow": ("performance", "medium", "Slow response", f"Server took over {SLOW_MS} ms to answer."),
    "page-heavy": ("performance", "low", "Heavy HTML", "HTML over 1.5 MB before any assets."),
    "cwv-lcp-poor": ("performance", "high", "LCP poor (Core Web Vital)", "Largest Contentful Paint over 4 s on mobile - fails Core Web Vitals."),
    "cwv-lcp-slow": ("performance", "medium", "LCP needs improvement", "Largest Contentful Paint 2.5-4 s on mobile."),
    "cwv-cls-poor": ("performance", "medium", "Layout shift (CLS) high", "Cumulative Layout Shift over 0.1 on mobile."),
    "cwv-inp-poor": ("performance", "medium", "INP poor", "Interaction to Next Paint over 200 ms for real users."),
    "psi-low": ("performance", "medium", "Low PageSpeed score", "Lighthouse mobile performance under 50."),
    "jsonld-invalid": ("schema", "medium", "Invalid JSON-LD", "Structured data that does not parse is ignored."),
    "jsonld-missing": ("schema", "low", "No structured data", "No JSON-LD found on the page."),
    "http-page": ("security", "high", "Served over HTTP", "Not HTTPS - browsers flag it and Google demotes it."),
    "mixed-content": ("security", "medium", "Mixed content", "HTTPS page loading http:// scripts or images."),
    "hsts-missing": ("security", "low", "No HSTS header", "Strict-Transport-Security keeps visitors on HTTPS."),
    "xcto-missing": ("security", "low", "No X-Content-Type-Options", "Prevents MIME sniffing. Cheap to add."),
    "thin-content": ("content", "medium", "Thin content", f"Under {THIN_WORDS} words of visible text."),
    "lang-missing": ("content", "low", "No lang attribute", "<html lang> tells search engines the language."),
}


def _issue(code, url, extra=None):
    cat, sev, label, detail = RULES[code]
    return {"code": code, "category": cat, "severity": sev, "label": label,
            "detail": detail, "url": url, **(extra or {})}


def _key(url):
    """Duplicate-URL key: scheme/case/slash/query stripped."""
    p = urlsplit(url)
    return (p.netloc.lower().replace("www.", "") + p.path.lower().rstrip("/")) or "/"


def analyze(crawl, pages):
    """pages: list[Page]. Returns {issues, per_page, score, breakdown, summary}."""
    by_url = {}
    for p in pages:
        by_url[p.url] = p
        if p.final_url:
            by_url.setdefault(p.final_url, p)
    html_ok = [p for p in pages if p.status_code == 200 and p.is_html and not p.fetch_error]
    indexable = [p for p in html_ok if p.indexable]
    sitemap_set = {normalize(u) for u in crawl.sitemap_urls if normalize(u)}
    externals = crawl.external_checks or {}

    def resolve(link):
        """Follow redirect rows to the page that actually renders."""
        target = by_url.get(link)
        for _ in range(MAX_HOPS):
            if not target or not target.redirect_chain or target.final_url in ("", target.url):
                return target
            target = by_url.get(target.final_url)
        return target

    inbound = defaultdict(set)
    for p in html_ok:
        for link in p.internal_links:
            target = resolve(link)
            if target and target.pk != p.pk:
                inbound[target.pk].add(p.pk)

    issues = []
    add = lambda code, page, **extra: issues.append(_issue(code, page.url, extra))

    # status / redirects / fetch
    for p in pages:
        if p.fetch_error and "loop" in p.fetch_error:
            add("redirect-loop", p)
        elif p.fetch_error and not p.robots_blocked:
            add("fetch-error", p, error=p.fetch_error)
        elif p.status_code and p.status_code >= 500:
            add("http-5xx", p, status=p.status_code)
        elif p.status_code and 400 <= p.status_code < 500:
            add("http-4xx", p, status=p.status_code)
        if len(p.redirect_chain) > 1:
            add("redirect-chain", p, hops=len(p.redirect_chain), final=p.final_url)
        if p.robots_blocked and p.in_sitemap:
            add("robots-blocked", p)

    # sitemap
    if not crawl.sitemap_url:
        issues.append(_issue("sitemap-missing", crawl.site))
    for p in pages:
        if p.in_sitemap:
            if p.status_code != 200 or p.redirect_chain:
                add("sitemap-url-broken", p, status=p.status_code)
            elif "noindex" in (p.meta_robots or "").lower():
                add("sitemap-url-noindex", p)
    if crawl.sitemap_url:
        for p in indexable:
            if normalize(p.url) not in sitemap_set and normalize(p.final_url) not in sitemap_set:
                add("not-in-sitemap", p)

    # per-page on-page rules
    titles, metas, h1s, hashes, ukeys = Counter(), Counter(), Counter(), Counter(), defaultdict(list)
    for p in html_ok:
        if "noindex" in (p.meta_robots or "").lower():
            add("noindex", p)
        if not p.canonical:
            add("canonical-missing", p)
        else:
            target = by_url.get(p.canonical)
            if normalize(p.canonical) not in (normalize(p.url), normalize(p.final_url)):
                if target is None or not target.indexable:
                    add("canonical-broken", p, canonical=p.canonical)
                else:
                    add("canonical-other", p, canonical=p.canonical)
        if not p.title:
            add("title-missing", p)
        elif len(p.title) > TITLE_MAX:
            add("title-long", p, length=len(p.title))
        elif len(p.title) < TITLE_MIN:
            add("title-short", p, length=len(p.title))
        if not p.meta_description:
            add("meta-missing", p)
        elif len(p.meta_description) > META_MAX:
            add("meta-long", p, length=len(p.meta_description))
        elif len(p.meta_description) < META_MIN:
            add("meta-short", p, length=len(p.meta_description))
        if not p.h1:
            add("h1-missing", p)
        elif len(p.h1) > 1:
            add("h1-multiple", p, count=len(p.h1))
        if p.h2_count == 0 and p.word_count > 300:
            add("h2-missing", p)
        if p.word_count < THIN_WORDS:
            add("thin-content", p, words=p.word_count)
        if not p.lang:
            add("lang-missing", p)
        if p.images_missing_alt:
            add("img-missing-alt", p, count=p.images_missing_alt, total=p.images_total)
        if p.response_ms and p.response_ms > SLOW_MS:
            add("page-slow", p, ms=p.response_ms)
        if p.bytes > HEAVY_BYTES:
            add("page-heavy", p, bytes=p.bytes)
        if p.lcp_ms is not None and p.lcp_ms > 4000:
            add("cwv-lcp-poor", p, lcp_ms=p.lcp_ms)
        elif p.lcp_ms is not None and p.lcp_ms > 2500:
            add("cwv-lcp-slow", p, lcp_ms=p.lcp_ms)
        if p.cls is not None and p.cls > 0.1:
            add("cwv-cls-poor", p, cls=p.cls)
        if p.inp_ms is not None and p.inp_ms > 200:
            add("cwv-inp-poor", p, inp_ms=p.inp_ms)
        if p.psi_score is not None and p.psi_score < 50:
            add("psi-low", p, score=p.psi_score)
        if p.jsonld_error:
            add("jsonld-invalid", p, error=p.jsonld_error)
        elif not p.jsonld_types:
            add("jsonld-missing", p)
        if p.final_url.startswith("http://"):
            add("http-page", p)
        if p.mixed_content:
            add("mixed-content", p, count=p.mixed_content)
        sec = p.security_headers or {}
        if p.final_url.startswith("https://") and not sec.get("strict-transport-security"):
            add("hsts-missing", p)
        if not sec.get("x-content-type-options"):
            add("xcto-missing", p)
        path = urlsplit(p.url).path
        if re.search(r"[A-Z]", path):
            add("url-uppercase", p)
        if "_" in path:
            add("url-underscore", p)
        if len(p.url) > URL_MAX:
            add("url-long", p, length=len(p.url))
        if urlsplit(p.url).query:
            add("url-query", p)
        if len([s for s in path.split("/") if s]) > DEEP_SEGMENTS:
            add("url-deep", p)
        if p.indexable:
            titles[p.title.lower()] += 1 if p.title else 0
            metas[p.meta_description.lower()] += 1 if p.meta_description else 0
            for h in p.h1:
                h1s[h.lower()] += 1
            hashes[p.text_hash] += 1
            ukeys[_key(p.url)].append(p.url)

        # links
        broken, redirected, ext_broken = [], [], []
        for link in p.internal_links:
            t = by_url.get(link)
            if not t:
                continue
            if t.fetch_error or (t.status_code and t.status_code >= 400):
                broken.append(link)
            elif t.redirect_chain and t.url == link:
                redirected.append(link)
        for link in p.external_links:
            code = externals.get(link)
            if code is not None and (code == 0 or code >= 400):
                ext_broken.append(link)
        if broken:
            add("broken-internal-link", p, targets=broken[:20], count=len(broken))
        if redirected:
            add("redirected-internal-link", p, targets=redirected[:20], count=len(redirected))
        if ext_broken:
            add("broken-external-link", p, targets=ext_broken[:20], count=len(ext_broken))
        if p.indexable and p.depth > 0:
            n = len(inbound.get(p.pk, ()))
            if n == 0:
                add("orphan", p)
            elif n < LOW_INBOUND:
                add("low-inbound", p, inbound=n)
        if p.indexable and p.depth >= DEEP_CLICKS:
            add("deep-click", p, depth=p.depth)
        if p.indexable and not any(resolve(l) for l in p.internal_links if l != p.url):
            add("no-outbound-internal", p)

    # duplicates
    for p in indexable:
        if p.title and titles[p.title.lower()] > 1:
            add("duplicate-title", p, shared_by=titles[p.title.lower()])
        if p.meta_description and metas[p.meta_description.lower()] > 1:
            add("duplicate-meta", p, shared_by=metas[p.meta_description.lower()])
        if p.h1 and h1s[p.h1[0].lower()] > 1:
            add("duplicate-h1", p, shared_by=h1s[p.h1[0].lower()])
        if p.word_count >= THIN_WORDS and hashes[p.text_hash] > 1:
            add("duplicate-content", p, shared_by=hashes[p.text_hash])
    for key, urls in ukeys.items():
        if len(set(urls)) > 1:
            for u in urls:
                issues.append(_issue("duplicate-url", u, {"variants": urls}))

    return summarize(crawl, pages, issues)


def summarize(crawl, pages, issues):
    per_page = defaultdict(list)
    for i in issues:
        per_page[i["url"]].append(i)
    scored = {}
    for p in pages:
        penalty = sum(WEIGHT[i["severity"]] for i in per_page.get(p.url, []))
        scored[p.url] = max(0, 100 - penalty)
    html_pages = [p for p in pages if p.status_code == 200 and p.is_html]
    site_score = round(sum(scored[p.url] for p in html_pages) / len(html_pages)) if html_pages else 100

    by_cat = defaultdict(lambda: {"high": 0, "medium": 0, "low": 0})
    for i in issues:
        by_cat[i["category"]][i["severity"]] += 1
    groups = defaultdict(list)
    for i in issues:
        groups[i["code"]].append(i)
    grouped = sorted(
        [{"code": code, "category": RULES[code][0], "severity": RULES[code][1],
          "label": RULES[code][2], "detail": RULES[code][3], "count": len(items),
          "pages": [{k: v for k, v in i.items() if k not in ("code", "category", "severity", "label", "detail")}
                    for i in items[:200]]}
         for code, items in groups.items()],
        key=lambda g: (["high", "medium", "low"].index(g["severity"]), -g["count"]),
    )
    return {
        "score": site_score,
        "summary": {
            "pages": len(pages),
            "html_pages": len(html_pages),
            "indexable": sum(1 for p in html_pages if p.indexable),
            "issues": len(issues),
            "high": sum(1 for i in issues if i["severity"] == "high"),
            "medium": sum(1 for i in issues if i["severity"] == "medium"),
            "low": sum(1 for i in issues if i["severity"] == "low"),
            "affected_pages": len(per_page),
        },
        "breakdown": dict(by_cat),
        "issues": grouped,
        "page_scores": scored,
        "per_page": dict(per_page),
    }
