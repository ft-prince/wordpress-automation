"""Core Web Vitals via PageSpeed Insights (free key). Stores mobile lab + field metrics on
the latest crawl's Page rows; technical.py turns them into issues."""
import json
import urllib.error
import urllib.parse
import urllib.request

from django.utils import timezone

from core import secrets, sites
from core.models import Crawl

API = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
DEFAULT_PAGES = 30


def configured():
    return bool(secrets._parse().get("GOOGLE_API_KEY"))


def measure(url, strategy="mobile"):
    key = secrets._parse().get("GOOGLE_API_KEY")
    if not key:
        raise ValueError("add GOOGLE_API_KEY (with PageSpeed Insights API enabled) in Secrets")
    q = urllib.parse.urlencode({"key": key, "url": url, "strategy": strategy, "category": "performance"})
    try:
        with urllib.request.urlopen(f"{API}?{q}", timeout=120) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"PageSpeed {exc.code}: {exc.read().decode('utf8', 'replace')[:200]}")
    audits = data["lighthouseResult"]["audits"]
    field = (data.get("loadingExperience") or {}).get("metrics") or {}
    ms = lambda k: round(audits[k]["numericValue"]) if k in audits and audits[k].get("numericValue") is not None else None
    return {
        "psi_score": round((data["lighthouseResult"]["categories"]["performance"]["score"] or 0) * 100),
        "lcp_ms": ms("largest-contentful-paint"), "cls": round(audits.get("cumulative-layout-shift", {}).get("numericValue") or 0, 3),
        "tbt_ms": ms("total-blocking-time"),
        "inp_ms": (field.get("INTERACTION_TO_NEXT_PAINT") or {}).get("percentile"),
    }


def run(site=None, max_pages=DEFAULT_PAGES, log=print):
    """Measure the most important indexable pages of the latest crawl."""
    site_id = sites.env_for(site)["_site_id"]
    crawl = Crawl.objects.filter(site=site_id, status="done").order_by("-id").first()
    if not crawl:
        raise ValueError("crawl the site first")
    pages = sorted((p for p in crawl.pages.all() if p.indexable), key=lambda p: (p.depth, -p.word_count))[:max_pages]
    log(f"pagespeed: {len(pages)} pages (mobile)")
    done = 0
    for p in pages:
        try:
            metrics = measure(p.final_url or p.url)
        except (RuntimeError, ValueError) as exc:
            log(f"  {p.url}: {exc}")
            continue
        for k, v in metrics.items():
            setattr(p, k, v)
        p.psi_at = timezone.now()
        p.save(update_fields=[*metrics, "psi_at"])
        done += 1
        log(f"  {p.url}: score {metrics['psi_score']} LCP {metrics['lcp_ms']}ms CLS {metrics['cls']}")
    return done
