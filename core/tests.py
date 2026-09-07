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
