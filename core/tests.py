"""One runnable check per non-trivial piece: HTML parser, technical rules, on-page
apply guard. `python manage.py test core`."""
from django.test import TestCase

from core import crawl, technical
from core.models import Crawl, Page

HTML = """<html lang="en"><head><title>Hello World Page Title Here</title>
<meta name="description" content="A description that is long enough to pass the seventy character minimum rule.">
<link rel="canonical" href="/a/"><script type="application/ld+json">{"@type":"Article"}</script></head>
<body><h1>Main</h1><h2>Sub</h2><p>some words here</p>
<a href="/b/">b</a><a href="https://other.example/x">ext</a><img src="x.png"><img src="y.png" alt="y">
<script src="http://cdn.example/a.js"></script></body></html>"""


class ParserTest(TestCase):
    def test_parses_head_and_body(self):
        page, links = crawl._page_from(
            "https://site.example/a/",
            {"status": 200, "headers": {"content-type": "text/html; charset=utf-8"},
             "body": HTML.encode(), "ms": 10, "chain": [], "final_url": "https://site.example/a/"},
            "site.example", 0, True, False)
        self.assertEqual(page.title, "Hello World Page Title Here")
        self.assertEqual(page.h1, ["Main"])
        self.assertEqual(page.canonical, "https://site.example/a/")
        self.assertEqual(page.images_missing_alt, 1)
        self.assertEqual(page.jsonld_types, ["Article"])
        self.assertEqual(page.mixed_content, 1)
        self.assertEqual(links, ["https://site.example/b/"])
        self.assertEqual(page.external_links, ["https://other.example/x"])

    def test_normalize(self):
        self.assertEqual(crawl.normalize("/x?y=1#frag", "https://A.example/p/"), "https://a.example/x?y=1")
        self.assertIsNone(crawl.normalize("mailto:a@b"))


class RulesTest(TestCase):
    def _page(self, c, url, **kw):
        base = dict(status_code=200, content_type="text/html", title="A perfectly sized title for testing",
                    meta_description="x" * 90, h1=["h"], word_count=400, canonical=url, lang="en",
                    jsonld_types=["WebPage"], security_headers={"strict-transport-security": "1", "x-content-type-options": "nosniff"},
                    internal_links=[], in_sitemap=True)
        base.update(kw)
        return Page.objects.create(crawl=c, url=url, final_url=url, **base)

    def test_flags_the_obvious(self):
        c = Crawl.objects.create(site="t", status="done", sitemap_url="https://s.example/sitemap.xml",
                                 sitemap_urls=["https://s.example/", "https://s.example/a/"],
                                 external_checks={"https://dead.example/": 404})
        home = self._page(c, "https://s.example/", internal_links=["https://s.example/a/", "https://s.example/missing/"],
                          external_links=["https://dead.example/"], depth=0)
        self._page(c, "https://s.example/a/", h1=[], title="", meta_description="", depth=1,
                   internal_links=["https://s.example/"])
        self._page(c, "https://s.example/missing/", status_code=404, depth=1, in_sitemap=False)
        self._page(c, "https://s.example/orphan/", depth=2, in_sitemap=False, word_count=50)
        report = technical.analyze(c, list(c.pages.all()))
        codes = {g["code"] for g in report["issues"]}
        for expected in ("http-4xx", "broken-internal-link", "broken-external-link", "h1-missing",
                         "title-missing", "meta-missing", "orphan", "not-in-sitemap", "thin-content"):
            self.assertIn(expected, codes, expected)
        self.assertNotIn("orphan", {i["code"] for i in report["per_page"][home.url]})
        self.assertLess(report["page_scores"]["https://s.example/a/"], report["page_scores"][home.url])
        self.assertTrue(0 <= report["score"] <= 100)

    def test_duplicates(self):
        c = Crawl.objects.create(site="t", status="done", sitemap_url="x", sitemap_urls=[])
        for u in ("https://s.example/p1/", "https://s.example/p2/"):
            self._page(c, u, title="Same title everywhere on the site", text_hash="abc", in_sitemap=False, depth=0)
        codes = {g["code"] for g in technical.analyze(c, list(c.pages.all()))["issues"]}
        self.assertIn("duplicate-title", codes)
        self.assertIn("duplicate-content", codes)


class ApplyGuardTest(TestCase):
    def test_unmapped_page_cannot_apply(self):
        from core import seo

        c = Crawl.objects.create(site="t", status="done")
        p = Page.objects.create(crawl=c, url="https://s.example/", final_url="https://s.example/")
        with self.assertRaises(ValueError):
            seo.apply_onpage(p.pk, "title", "New")
        with self.assertRaises(ValueError):
            seo.apply_onpage(p.pk, "content", "New")


class ChangeGateTest(TestCase):
    """WordPress is faked: a dict per item. Proves propose -> apply -> rollback round-trips."""

    def setUp(self):
        from unittest import mock

        from core import changes, sites

        self.items = {("posts", 5): {"title": "Old title", "excerpt_raw": "old meta", "supports_excerpt": True,
                                     "content_raw": "", "slug": "old", "meta_desc": ""}}

        def get_item(base, item_id, site=None):
            return dict(self.items[(base, item_id)])

        def update_item(base, item_id, fields, site=None):
            row = self.items[(base, item_id)]
            for k, v in fields.items():
                row["excerpt_raw" if k == "excerpt" else k] = v
            return {"id": item_id, "saved": True}

        patches = [mock.patch.object(changes.wp_api, "get_item", get_item),
                   mock.patch.object(changes.wp_api, "update_item", update_item),
                   mock.patch.object(sites, "env_for", lambda site=None: {"_site_id": "t", "WEBSITE_LINK": "https://t"})]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_apply_then_rollback(self):
        from core import changes

        c = changes.propose("title", "posts", 5, "New title", reason="test")
        self.assertEqual((c["status"], c["before"]), ("proposed", "Old title"))
        self.assertEqual(self.items[("posts", 5)]["title"], "Old title")  # nothing written yet
        changes.apply(c["id"])
        self.assertEqual(self.items[("posts", 5)]["title"], "New title")
        changes.rollback(c["id"])
        self.assertEqual(self.items[("posts", 5)]["title"], "Old title")
        self.assertEqual(changes.listing()[0]["status"], "rolled_back")

    def test_meta_lands_on_excerpt_when_supported(self):
        from core import changes

        c = changes.propose_and_apply("meta", "posts", 5, "A new description")
        self.assertEqual(c["field"], "excerpt")
        self.assertEqual(self.items[("posts", 5)]["excerpt_raw"], "A new description")

    def test_noop_and_double_apply_rejected(self):
        from core import changes

        with self.assertRaises(ValueError):
            changes.propose("title", "posts", 5, "Old title")
        c = changes.propose_and_apply("title", "posts", 5, "X")
        with self.assertRaises(ValueError):
            changes.apply(c["id"])


class BriefQaTest(TestCase):
    def test_deterministic_checks_read_the_draft(self):
        from core import briefs
        from core.models import Brief

        kw = "server response time"
        body = "<h2>Why server response time matters</h2>" + "<p>" + (f"{kw} is the first thing to read. " + "Plain words follow here. " * 12) + "</p>"
        body += "<h2>Measuring it</h2><p>" + "More sentences about latency and percentiles. " * 30 + "</p>"
        body += '<h2>Next steps</h2><p>Read <a href="https://t/blog/x/">our guide</a>. ' + "Still more useful text. " * 20 + "</p>"
        b = Brief.objects.create(site="t", title="t", primary_keyword=kw, word_target=200,
                                 internal_links=[{"title": "x", "url": "https://t/blog/x/"}],
                                 draft_title="How to Read Server Response Time Metrics",
                                 draft_meta="Learn how to read server response time, latency percentiles and TTFB so you can find and fix your slowest pages quickly.",
                                 draft_html=body)
        checks = {c["code"]: c["ok"] for c in briefs.deterministic_checks(b)}
        for code in ("title-has-keyword", "title-length", "meta-length", "keyword-early", "keyword-in-h2",
                     "length", "headings", "internal-links", "no-h1", "no-dashes"):
            self.assertTrue(checks[code], code)
        b.draft_html = "<h1>x</h1><p>short – text</p>"
        checks = {c["code"]: c["ok"] for c in briefs.deterministic_checks(b)}
        self.assertFalse(checks["no-h1"])
        self.assertFalse(checks["no-dashes"])
        self.assertFalse(checks["length"])

    def test_approve_never_publishes(self):
        from core import briefs

        with self.assertRaises(ValueError):
            briefs.approve(1, status="publish")


class ProfileTest(TestCase):
    def test_save_validates_shape(self):
        from unittest import mock

        from core import profile, sites

        with mock.patch.object(sites, "env_for", lambda site=None: {"_site_id": "t", "WEBSITE_LINK": "https://t"}):
            self.assertTrue(profile.get()["is_empty"])
            with self.assertRaises(ValueError):
                profile.save({"products": "not a list"})
            saved = profile.save({"name": "Acme", "products": ["Widget"], "facts": ["Founded 2020"]})
            self.assertFalse(saved["is_empty"])
            self.assertIn("Founded 2020", profile.context())


class KeywordOpsTest(TestCase):
    """Manual controls + cannibalization + gaps need no model."""

    def setUp(self):
        from unittest import mock

        from core import sites

        p = mock.patch.object(sites, "env_for", lambda site=None: {"_site_id": "t", "WEBSITE_LINK": "https://t"})
        p.start()
        self.addCleanup(p.stop)

    def test_merge_split_primary(self):
        from core import keywords
        from core.models import Cluster, Keyword

        a = Cluster.objects.create(site="t", name="A", intent="commercial")
        b = Cluster.objects.create(site="t", name="B", intent="commercial")
        k1 = Keyword.objects.create(site="t", text="cctv analytics", cluster=a, is_primary=True, relevance=90)
        k2 = Keyword.objects.create(site="t", text="cctv ai software", cluster=a, relevance=70)
        k3 = Keyword.objects.create(site="t", text="camera ai", cluster=b, is_primary=True, relevance=60)
        merged = keywords.merge(a.pk, b.pk)
        self.assertEqual(len(merged["keywords"]), 3)
        self.assertFalse(Cluster.objects.filter(pk=b.pk).exists())
        self.assertEqual(sum(1 for k in merged["keywords"] if k["is_primary"]), 1)
        new = keywords.split(a.pk, [k2.pk, k3.pk], "Camera software")
        self.assertEqual(len(new["keywords"]), 2)
        self.assertTrue(any(k["is_primary"] for k in new["keywords"]))
        self.assertEqual(Keyword.objects.get(pk=k1.pk).cluster_id, a.pk)
        keywords.set_primary(k3.pk)
        self.assertFalse(Keyword.objects.get(pk=k2.pk).is_primary)

    def test_cannibalization_and_gaps(self):
        from core import keywords
        from core.models import Cluster, Keyword

        c1 = Cluster.objects.create(site="t", name="buy", intent="commercial", action="existing", target_url="https://t/p/", priority=80)
        c2 = Cluster.objects.create(site="t", name="learn", intent="informational", action="existing", target_url="https://t/p/", priority=40)
        c3 = Cluster.objects.create(site="t", name="pricing", intent="transactional", action="new", priority=90)
        c4 = Cluster.objects.create(site="t", name="how to", intent="informational", action="new", parent_topic="learn", priority=30)
        Keyword.objects.create(site="t", text="cctv analytics", cluster=c1, is_primary=True, found_on=["https://t/a/", "https://t/b/"])
        Keyword.objects.create(site="t", text="cctv guide", cluster=c2, found_on=["https://t/q/"])
        issues = {i["type"] for i in keywords.cannibalization()}
        self.assertEqual(issues, {"mixed-intent-target", "shared-primary-keyword", "wrong-page-targeting"})
        g = keywords.gaps()
        self.assertEqual([c["name"] for c in g["missing_commercial_pages"]], ["pricing"])
        self.assertEqual([c["name"] for c in g["supporting_content"]], ["how to"])
        self.assertEqual(g["unmapped"], 0)

    def test_harvest_reads_crawl_titles(self):
        from core import keywords
        from core.models import Crawl, Keyword, Page

        c = Crawl.objects.create(site="t", status="done")
        Page.objects.create(crawl=c, url="https://t/x/", final_url="https://t/x/", status_code=200, content_type="text/html",
                            word_count=300, title="Crowd People Analytics - Brand", h1=["Crowd People Analytics"])
        self.assertEqual(keywords.harvest(), 1)
        kw = Keyword.objects.get(site="t", text="crowd people analytics")
        self.assertEqual(kw.found_on, ["https://t/x/"])


class InsightsTest(TestCase):
    """Rules over synthetic GSC/GA4 rows: each rule fires on the row built to trigger it."""

    def setUp(self):
        from datetime import date, timedelta
        from unittest import mock

        from core import sites
        from core.models import Ga4Row, GscRow, Keyword

        p = mock.patch.object(sites, "env_for", lambda site=None: {"_site_id": "t", "WEBSITE_LINK": "https://t"})
        p.start()
        self.addCleanup(p.stop)
        today = date.today() - timedelta(days=5)
        prev = today - timedelta(days=35)
        rows = [
            # striking distance
            GscRow(site="t", date=today, query="edge ai cameras", page="https://t/a/", clicks=2, impressions=100, position=12),
            # weak CTR at position 3
            GscRow(site="t", date=today, query="cctv analytics", page="https://t/b/", clicks=1, impressions=300, position=3),
            # cannibalization: two pages share a query
            GscRow(site="t", date=today, query="people counting", page="https://t/c/", clicks=5, impressions=60, position=6),
            GscRow(site="t", date=today, query="people counting", page="https://t/d/", clicks=3, impressions=50, position=9),
            # ranking decline on /e/
            GscRow(site="t", date=prev, query="q", page="https://t/e/", clicks=10, impressions=100, position=4),
            GscRow(site="t", date=today, query="q", page="https://t/e/", clicks=2, impressions=100, position=11),
        ]
        GscRow.objects.bulk_create(rows)
        Keyword.objects.create(site="t", text="cctv analytics")
        Ga4Row.objects.bulk_create([
            Ga4Row(site="t", date=prev, landing_page="https://t/e/", channel="Organic Search", sessions=100),
            Ga4Row(site="t", date=today, landing_page="https://t/e/", channel="Organic Search", sessions=40),
        ])

    def test_rules_fire(self):
        from core import insights

        self.assertEqual(insights.page1_opportunities()[0]["query"], "edge ai cameras")  # most impressions first
        ctr = insights.ctr_opportunities()
        self.assertEqual(ctr[0]["page"], "https://t/b/")
        self.assertGreater(ctr[0]["missed_clicks"], 20)
        can = insights.cannibalization()
        self.assertEqual(can[0]["query"], "people counting")
        self.assertEqual(len(can[0]["pages"]), 2)
        new = {r["query"] for r in insights.new_keywords()}
        self.assertIn("people counting", new)
        self.assertNotIn("cctv analytics", new)  # already known
        self.assertEqual(insights.ranking_decline()[0]["page"], "https://t/e/")
        drop = insights.traffic_decline()[0]
        self.assertEqual((drop["page"], drop["drop"]), ("https://t/e/", 60))
        plan = {p["page"]: p["action"] for p in insights.refresh_plan()}
        self.assertEqual(plan["https://t/e/"], "Refresh")
        self.assertEqual(plan["https://t/b/"], "Re-optimize")
        self.assertEqual(plan["https://t/d/"], "Merge")
        s = insights.summary()
        self.assertEqual(s["cannibalization"], 1)

    def test_report_totals(self):
        from core import insights

        r = insights.traffic_report()
        self.assertEqual(r["organic"]["now"]["sessions"], 40)
        self.assertEqual(r["organic"]["before"]["sessions"], 100)
        self.assertEqual(r["search"]["now"]["clicks"], 13)


class RolesSchemaLinksCostsTest(TestCase):
    def test_roles_and_gate(self):
        from django.contrib.auth.models import User
        from ninja.errors import HttpError

        from core import roles

        viewer = User.objects.create_user("v", password="password123")
        seo = roles.create("s", "password123", "seo")
        self.assertEqual(roles.role_of(viewer), "viewer")
        self.assertEqual(roles.role_of(User.objects.get(pk=seo["id"])), "seo")

        class R:  # minimal request stand-in
            def __init__(self, u):
                self.auth = u
        with self.assertRaises(HttpError):
            roles.require(R(viewer), "approve")
        self.assertEqual(roles.require(R(User.objects.get(pk=seo["id"])), "approve"), "seo")
        with self.assertRaises(HttpError):
            roles.require(R(User.objects.get(pk=seo["id"])), "delete")
        with self.assertRaises(ValueError):
            roles.create("x", "short", "seo")

    def test_schema_from_draft(self):
        from unittest import mock

        from core import schema, sites
        from core.models import Brief

        html = "<h2>Intro</h2><p>x</p><h2>FAQ</h2><h3>Is it free?</h3><p>Yes, <b>always</b>.</p><h3>Why?</h3><p>Because.</p>"
        b = Brief.objects.create(site="t", title="T", draft_title="Headline here", draft_meta="desc", draft_html=html, primary_keyword="k")
        with mock.patch.object(sites, "env_for", lambda site=None: {"_site_id": "t", "WEBSITE_LINK": "https://t.example", "language": "en"}):
            out = schema.for_brief(b.pk)
        self.assertEqual(out["types"], ["Article", "FAQPage"])
        self.assertEqual(out["errors"], [])
        faq = out["jsonld"]["@graph"][1]["mainEntity"]
        self.assertEqual(faq[0]["acceptedAnswer"]["text"], "Yes, always.")
        injected = schema.inject(html, out["jsonld"])
        self.assertEqual(injected.count("application/ld+json"), 1)
        self.assertEqual(schema.inject(injected, out["jsonld"]).count("application/ld+json"), 1)  # idempotent

    def test_apply_outbound_links(self):
        from core import linking
        from core.models import Brief

        b = Brief.objects.create(site="t", title="T", draft_html="<p>Our crowd analytics tool counts people.</p><p>More.</p>",
                                 link_plan={"outbound": [{"url": "https://t/crowd/", "anchor": "crowd analytics"},
                                                         {"url": "https://t/other/", "anchor": "not in text"}]})
        out = linking.apply_outbound(b.pk)
        b.refresh_from_db()
        self.assertEqual(out["linked"], ["https://t/crowd/", "https://t/other/"])
        self.assertIn('<a href="https://t/crowd/">crowd analytics</a>', b.draft_html)
        self.assertIn('<a href="https://t/other/">not in text</a>', b.draft_html)
        self.assertEqual(b.draft_html.count("https://t/crowd/"), 1)

    def test_cost_ledger(self):
        from core import costs
        from core.models import LlmCall

        costs.record({"model": "openai/gpt-oss-120b", "usage": {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000}}, "test")
        costs.record({"bogus": True})  # must not raise
        self.assertEqual(LlmCall.objects.count(), 1)
        self.assertAlmostEqual(costs.summary()["today"]["usd"], 0.75)


class SerpPagespeedTest(TestCase):
    def test_parse_tool_results_and_dedupe(self):
        from core import serp

        tools = [{"type": "browser_search", "search_results": {"results": [
            {"title": "A", "url": "https://www.acme.com/x", "content": "s"},
            {"title": "Y", "url": "https://www.youtube.com/watch?v=1"},
            {"title": "A again", "url": "https://www.acme.com/x"},
            {"title": "B", "url": "https://b.example/"}]}}]
        rows = serp._dedupe(serp.parse_tool_results(tools))
        self.assertEqual([r["domain"] for r in rows], ["acme.com", "b.example"])
        self.assertEqual(rows[0]["snippet"], "s")

    def test_competitors_aggregate(self):
        from unittest import mock

        from core import serp, sites
        from core.models import Cluster

        with mock.patch.object(sites, "env_for", lambda site=None: {"_site_id": "t", "WEBSITE_LINK": "https://t.example"}):
            Cluster.objects.create(site="t", name="a", serp={"keyword": "k1", "results": [
                {"url": "https://rival.com/1", "domain": "rival.com", "rank": 1}, {"url": "https://t.example/", "domain": "t.example", "rank": 2}]})
            Cluster.objects.create(site="t", name="b", serp={"keyword": "k2", "results": [
                {"url": "https://rival.com/2", "domain": "rival.com", "rank": 3}, {"url": "https://other.io/", "domain": "other.io", "rank": 1}]})
            out = serp.competitors()
        self.assertEqual(out[0]["domain"], "rival.com")
        self.assertEqual((out[0]["clusters"], out[0]["best_rank"], out[0]["keywords"]), (2, 1, ["k1", "k2"]))
        self.assertNotIn("t.example", [c["domain"] for c in out])

    def test_cwv_rules(self):
        from core import technical
        from core.models import Crawl, Page

        c = Crawl.objects.create(site="t", status="done", sitemap_url="x")
        Page.objects.create(crawl=c, url="https://t/", final_url="https://t/", status_code=200, content_type="text/html",
                            title="A perfectly sized title for testing here", meta_description="m" * 90, h1=["h"], word_count=400,
                            canonical="https://t/", lang="en", jsonld_types=["WebPage"], lcp_ms=5200, cls=0.3, psi_score=40, inp_ms=350)
        codes = {g["code"] for g in technical.analyze(c, list(c.pages.all()))["issues"]}
        self.assertTrue({"cwv-lcp-poor", "cwv-cls-poor", "psi-low", "cwv-inp-poor"} <= codes)
        self.assertNotIn("cwv-lcp-slow", codes)
