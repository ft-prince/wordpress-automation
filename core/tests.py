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
