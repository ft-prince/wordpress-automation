"""Search performance rules over synced GSC/GA4 rows. Pure ORM aggregation, no model calls.
Thresholds are named so an SEO can read them; the automation-rules sheet is these functions."""
from collections import defaultdict
from datetime import date, timedelta

from django.db.models import Count, F, FloatField, Sum

from core import sites
from core.models import Crawl, Ga4Row, GscRow, Keyword

WINDOW_DAYS = 28
PAGE1_LOW, PAGE1_HIGH = 8.0, 20.0        # "striking distance"
MIN_IMPRESSIONS = 20
CTR_MIN_IMPRESSIONS = 100
CTR_WEAK_FACTOR = 0.5                    # below half the expected CTR for that position
DECLINE_POSITIONS = 3.0
TRAFFIC_DROP = 0.30
MIN_SESSIONS = 20
CANNIBAL_SHARE = 0.20
EXPECTED_CTR = {1: .28, 2: .15, 3: .11, 4: .08, 5: .07, 6: .05, 7: .04, 8: .035, 9: .03, 10: .025}


def _site(site):
    return sites.env_for(site)["_site_id"]


def _windows():
    end = date.today() - timedelta(days=3)
    cur = (end - timedelta(days=WINDOW_DAYS), end)
    prev = (cur[0] - timedelta(days=WINDOW_DAYS + 1), cur[0] - timedelta(days=1))
    return cur, prev


def _agg(site_id, window, *dims):
    """Sum clicks/impressions, impression-weighted position, grouped by dims."""
    rows = (GscRow.objects.filter(site=site_id, date__gte=window[0], date__lte=window[1])
            .values(*dims).annotate(clicks_sum=Sum("clicks"), imp_sum=Sum("impressions"),
                                    wpos=Sum(F("position") * F("impressions"), output_field=FloatField())))
    out = []
    for r in rows:
        imp = r["imp_sum"] or 0
        out.append({**{d: r[d] for d in dims}, "clicks": r["clicks_sum"] or 0, "impressions": imp,
                    "position": round(r["wpos"] / imp, 1) if imp else 0,
                    "ctr": round((r["clicks_sum"] or 0) / imp, 4) if imp else 0})
    return out


def page1_opportunities(site=None, limit=50):
    """Positions 8-20 with real impressions: a content/link push moves these to page 1."""
    cur, _ = _windows()
    rows = [r for r in _agg(_site(site), cur, "query", "page")
            if PAGE1_LOW <= r["position"] <= PAGE1_HIGH and r["impressions"] >= MIN_IMPRESSIONS]
    return sorted(rows, key=lambda r: -r["impressions"])[:limit]


def ctr_opportunities(site=None, limit=50):
    """Page-1 rankings that get far fewer clicks than the position should earn: title/meta job."""
    cur, _ = _windows()
    out = []
    for r in _agg(_site(site), cur, "page"):
        pos = round(r["position"])
        if 1 <= pos <= 10 and r["impressions"] >= CTR_MIN_IMPRESSIONS:
            expected = EXPECTED_CTR[pos]
            if r["ctr"] < expected * CTR_WEAK_FACTOR:
                out.append({**r, "expected_ctr": expected, "missed_clicks": round((expected - r["ctr"]) * r["impressions"])})
    return sorted(out, key=lambda r: -r["missed_clicks"])[:limit]


def cannibalization(site=None, limit=50):
    """One query, several pages each taking a real share of impressions."""
    cur, _ = _windows()
    by_query = defaultdict(list)
    for r in _agg(_site(site), cur, "query", "page"):
        by_query[r["query"]].append(r)
    out = []
    for q, pages in by_query.items():
        total = sum(p["impressions"] for p in pages)
        if total < MIN_IMPRESSIONS or len(pages) < 2:
            continue
        shares = [p for p in pages if p["impressions"] / total >= CANNIBAL_SHARE]
        if len(shares) >= 2:
            out.append({"query": q, "impressions": total, "clicks": sum(p["clicks"] for p in pages),
                        "pages": sorted(({"page": p["page"], "impressions": p["impressions"], "position": p["position"]} for p in shares),
                                        key=lambda p: -p["impressions"])})
    return sorted(out, key=lambda r: -r["impressions"])[:limit]


def new_keywords(site=None, limit=100):
    """Queries Google already shows the site for that the keyword database does not know."""
    cur, _ = _windows()
    site_id = _site(site)
    known = set(Keyword.objects.filter(site=site_id).values_list("text", flat=True))
    rows = [r for r in _agg(site_id, cur, "query", "page") if r["impressions"] >= 10 and r["query"].lower() not in known]
    best = {}
    for r in rows:  # keep the best page per query
        if r["query"] not in best or r["impressions"] > best[r["query"]]["impressions"]:
            best[r["query"]] = r
    return sorted(best.values(), key=lambda r: -r["impressions"])[:limit]


def ranking_decline(site=None, limit=50):
    """Pages whose weighted position got worse by 3+ between the two 28-day windows."""
    cur, prev = _windows()
    site_id = _site(site)
    now = {r["page"]: r for r in _agg(site_id, cur, "page")}
    before = {r["page"]: r for r in _agg(site_id, prev, "page")}
    out = []
    for page, b in before.items():
        n = now.get(page)
        if not n or b["impressions"] < MIN_IMPRESSIONS or n["impressions"] < MIN_IMPRESSIONS:
            continue
        if n["position"] - b["position"] >= DECLINE_POSITIONS:
            out.append({"page": page, "position_before": b["position"], "position_now": n["position"],
                        "clicks_before": b["clicks"], "clicks_now": n["clicks"], "impressions": n["impressions"]})
    return sorted(out, key=lambda r: -(r["position_now"] - r["position_before"]))[:limit]


def traffic_decline(site=None, limit=50):
    """Organic sessions per landing page down 30%+ window over window."""
    cur, prev = _windows()
    site_id = _site(site)

    def sessions(window):
        rows = (Ga4Row.objects.filter(site=site_id, channel="Organic Search", date__gte=window[0], date__lte=window[1])
                .values("landing_page").annotate(s=Sum("sessions"), c=Sum("conversions")))
        return {r["landing_page"]: (r["s"], r["c"]) for r in rows}

    now, before = sessions(cur), sessions(prev)
    out = []
    for page, (s_before, _) in before.items():
        s_now = now.get(page, (0, 0))[0]
        if s_before >= MIN_SESSIONS and (s_before - s_now) / s_before >= TRAFFIC_DROP:
            out.append({"page": page, "sessions_before": s_before, "sessions_now": s_now,
                        "drop": round((s_before - s_now) / s_before * 100)})
    return sorted(out, key=lambda r: -(r["sessions_before"] - r["sessions_now"]))[:limit]


def traffic_report(site=None):
    """Organic traffic + conversions, this window vs last, top landing pages."""
    cur, prev = _windows()
    site_id = _site(site)

    def totals(window):
        agg = Ga4Row.objects.filter(site=site_id, channel="Organic Search", date__gte=window[0], date__lte=window[1]) \
            .aggregate(sessions=Sum("sessions"), users=Sum("users"), conversions=Sum("conversions"))
        return {k: v or 0 for k, v in agg.items()}

    top = (Ga4Row.objects.filter(site=site_id, channel="Organic Search", date__gte=cur[0], date__lte=cur[1])
           .values("landing_page").annotate(sessions=Sum("sessions"), conversions=Sum("conversions")).order_by("-sessions")[:20])
    gsc = GscRow.objects.filter(site=site_id, date__gte=cur[0], date__lte=cur[1]).aggregate(
        clicks=Sum("clicks"), impressions=Sum("impressions"), queries=Count("query", distinct=True))
    gsc_prev = GscRow.objects.filter(site=site_id, date__gte=prev[0], date__lte=prev[1]).aggregate(clicks=Sum("clicks"), impressions=Sum("impressions"))
    daily = list(GscRow.objects.filter(site=site_id, date__gte=cur[0], date__lte=cur[1]).values("date")
                 .annotate(clicks=Sum("clicks"), impressions=Sum("impressions")).order_by("date"))
    return {"window": {"from": cur[0].isoformat(), "to": cur[1].isoformat(), "days": WINDOW_DAYS},
            "organic": {"now": totals(cur), "before": totals(prev)},
            "search": {"now": {k: v or 0 for k, v in gsc.items()}, "before": {k: v or 0 for k, v in gsc_prev.items()}},
            "daily": [{"date": d["date"].isoformat(), "clicks": d["clicks"], "impressions": d["impressions"]} for d in daily],
            "top_pages": list(top)}


def refresh_plan(site=None, limit=50):
    """Per page: Refresh / Expand / Re-optimize / Merge / Redirect / Leave, with the reason."""
    site_id = _site(site)
    reasons = defaultdict(list)
    for r in ranking_decline(site):
        reasons[r["page"]].append(("Refresh", f"position {r['position_before']} -> {r['position_now']}"))
    for r in traffic_decline(site):
        reasons[r["page"]].append(("Refresh", f"organic sessions down {r['drop']}%"))
    for r in ctr_opportunities(site):
        reasons[r["page"]].append(("Re-optimize", f"CTR {r['ctr']:.1%} vs {r['expected_ctr']:.0%} expected at position {round(r['position'])}"))
    expand = defaultdict(int)
    for r in new_keywords(site):
        expand[r["page"]] += 1
    for page, n in expand.items():
        if n >= 5:
            reasons[page].append(("Expand", f"appears for {n} queries the page does not target yet"))
    for r in cannibalization(site):
        for p in r["pages"][1:]:
            reasons[p["page"]].append(("Merge", f"competes with {r['pages'][0]['page']} for '{r['query']}'"))
    crawl = Crawl.objects.filter(site=site_id, status="done").order_by("-id").first()
    if crawl:
        dead = {p.url for p in crawl.pages.all() if p.status_code and p.status_code >= 400}
        cur, _ = _windows()
        for r in _agg(site_id, cur, "page"):
            if r["page"] in dead and r["clicks"] > 0:
                reasons[r["page"]].append(("Redirect", f"returns {next(p.status_code for p in crawl.pages.all() if p.url == r['page'])} but still gets {r['clicks']} clicks"))
    order = ["Redirect", "Merge", "Refresh", "Expand", "Re-optimize"]
    plan = [{"page": page, "action": sorted({a for a, _ in rs}, key=order.index)[0], "reasons": [f"{a}: {why}" for a, why in rs]}
            for page, rs in reasons.items()]
    return sorted(plan, key=lambda p: (order.index(p["action"]), -len(p["reasons"])))[:limit]


def summary(site=None):
    """Counts for the alert strip and the automation rules."""
    return {"page1": len(page1_opportunities(site)), "ctr": len(ctr_opportunities(site)),
            "cannibalization": len(cannibalization(site)), "new_keywords": len(new_keywords(site)),
            "ranking_decline": len(ranking_decline(site)), "traffic_decline": len(traffic_decline(site))}
