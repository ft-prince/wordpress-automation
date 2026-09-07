"""Site crawler, stdlib only. Seeds from the XML sitemap + homepage, follows internal
links breadth-first, records redirect chains, and parses each HTML page once into a
Page row. The technical audit (technical.py) reads only these rows, never the network.
ponytail: no JS rendering (needs a browser) - template pages are judged on served HTML."""
import gzip
import hashlib
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser

from django.utils import timezone

from core import sites
from core.models import Crawl, Page

USER_AGENT = "Mozilla/5.0 (compatible; PressPilotBot/1.0; +https://presspilot.local)"
TIMEOUT = 20
MAX_HOPS = 6
MAX_BODY = 3 * 1024 * 1024
SITEMAP_CANDIDATES = ("/wp-sitemap.xml", "/sitemap_index.xml", "/sitemap.xml")
SECURITY_HEADERS = ("strict-transport-security", "x-content-type-options", "x-frame-options",
                    "content-security-policy", "referrer-policy")
SKIP_EXT = re.compile(r"\.(jpe?g|png|gif|webp|svg|ico|pdf|zip|mp4|mp3|css|js|woff2?|ttf|xml|json)(\?|$)", re.I)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def normalize(url, base=None):
    """Absolute, fragment-free, host lower-cased. Returns None for non-http links."""
    if base:
        url = urllib.parse.urljoin(base, url)
    parts = urllib.parse.urlsplit(url.strip())
    if parts.scheme not in ("http", "https"):
        return None
    netloc = parts.netloc.lower()
    path = parts.path or "/"
    return urllib.parse.urlunsplit((parts.scheme, netloc, path, parts.query, ""))


def same_site(url, host):
    h = urllib.parse.urlsplit(url).netloc.lower()
    return h == host or h == f"www.{host}" or f"www.{h}" == host


class _Parser(HTMLParser):
    """One pass: head tags, headings, links, images, JSON-LD, visible text."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.meta_description = ""
        self.meta_robots = ""
        self.canonical = ""
        self.lang = ""
        self.h1 = []
        self.h2_count = 0
        self.links = []
        self.images_total = 0
        self.images_missing_alt = 0
        self.jsonld = []
        self.http_resources = 0
        self._text = []
        self._stack = []
        self._capture = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "html":
            self.lang = a.get("lang", "") or ""
        elif tag == "title" and not self.title:
            self._capture = "title"
        elif tag == "meta":
            name = (a.get("name") or "").lower()
            if name == "description":
                self.meta_description = (a.get("content") or "").strip()
            elif name == "robots":
                self.meta_robots = (a.get("content") or "").strip()
        elif tag == "link" and (a.get("rel") or "").lower() == "canonical":
            self.canonical = (a.get("href") or "").strip()
        elif tag == "h1":
            self._capture = "h1"
            self._buf = []
        elif tag == "h2":
            self.h2_count += 1
        elif tag == "a" and a.get("href"):
            self.links.append(a["href"])
        elif tag == "img":
            self.images_total += 1
            if not (a.get("alt") or "").strip():
                self.images_missing_alt += 1
            if (a.get("src") or "").startswith("http://"):
                self.http_resources += 1
        elif tag == "script":
            if (a.get("type") or "").lower() == "application/ld+json":
                self._capture = "jsonld"
                self._buf = []
            else:
                self._capture = "skip"
            if (a.get("src") or "").startswith("http://"):
                self.http_resources += 1
        elif tag == "style":
            self._capture = "skip"
        self._stack.append(tag)

    def handle_endtag(self, tag):
        if tag == "title" and self._capture == "title":
            self._capture = None
        elif tag == "h1" and self._capture == "h1":
            text = re.sub(r"\s+", " ", "".join(self._buf)).strip()
            self.h1.append(text)
            self._capture = None
        elif tag == "script" and self._capture in ("jsonld", "skip"):
            if self._capture == "jsonld":
                self.jsonld.append("".join(self._buf))
            self._capture = None
        elif tag == "style" and self._capture == "skip":
            self._capture = None

    def handle_data(self, data):
        if self._capture == "title":
            self.title += data
        elif self._capture in ("h1", "jsonld"):
            self._buf.append(data)
        elif self._capture == "skip":
            return
        else:
            self._text.append(data)

    @property
    def text(self):
        return re.sub(r"\s+", " ", " ".join(self._text)).strip()


def _fetch_once(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*"})
    started = time.time()
    try:
        with _opener.open(req, timeout=TIMEOUT) as resp:
            body = resp.read(MAX_BODY)
            return resp.status, dict(resp.headers), body, int((time.time() - started) * 1000)
    except urllib.error.HTTPError as exc:
        body = exc.read(MAX_BODY) if exc.code < 500 else b""
        return exc.code, dict(exc.headers), body, int((time.time() - started) * 1000)


def fetch(url):
    """Follow redirects by hand so the chain is recorded. Returns a dict or {'error'}."""
    chain = []
    current = url
    for _ in range(MAX_HOPS):
        try:
            status, headers, body, ms = _fetch_once(current)
        except Exception as exc:  # DNS, timeout, TLS, refused
            return {"error": str(exc)[:300], "chain": chain, "final_url": current}
        if 300 <= status < 400 and headers.get("Location"):
            chain.append({"url": current, "status": status})
            nxt = normalize(headers["Location"], current)
            if not nxt or any(h["url"] == nxt for h in chain):
                return {"error": "redirect loop", "chain": chain, "final_url": current, "status": status}
            current = nxt
            continue
        return {"status": status, "headers": {k.lower(): v for k, v in headers.items()},
                "body": body, "ms": ms, "chain": chain, "final_url": current}
    return {"error": "too many redirects", "chain": chain, "final_url": current}


def _sitemap_urls(root):
    """First sitemap that answers; sitemap indexes are followed one level."""
    for path in SITEMAP_CANDIDATES:
        url = root + path
        try:
            result = fetch(url)
        except Exception:
            continue
        if result.get("status") != 200:
            continue
        locs = _parse_sitemap(result["body"])
        if not locs:
            continue
        urls, subs = [], []
        for loc in locs:
            (subs if loc.endswith(".xml") or "sitemap" in loc.split("/")[-1] else urls).append(loc)
        for sub in subs[:40]:
            try:
                r = fetch(sub)
                if r.get("status") == 200:
                    urls += [u for u in _parse_sitemap(r["body"]) if not u.endswith(".xml")]
            except Exception:
                pass
        return url, sorted(set(urls))
    return "", []


def _parse_sitemap(body):
    if body[:2] == b"\x1f\x8b":
        body = gzip.decompress(body)
    try:
        tree = ET.fromstring(body)
    except ET.ParseError:
        return []
    return [el.text.strip() for el in tree.iter() if el.tag.endswith("loc") and el.text]


def _robots(root):
    rp = urllib.robotparser.RobotFileParser()
    txt = ""
    try:
        r = fetch(root + "/robots.txt")
        if r.get("status") == 200:
            txt = r["body"].decode("utf8", "replace")
            rp.parse(txt.splitlines())
        else:
            rp.parse([])
    except Exception:
        rp.parse([])
    return rp, txt


def _page_from(url, result, host, depth, in_sitemap, blocked):
    page = Page(url=url, depth=depth, in_sitemap=in_sitemap, robots_blocked=blocked,
                final_url=result.get("final_url", url), redirect_chain=result.get("chain", []))
    if "error" in result:
        page.fetch_error = result["error"]
        page.status_code = result.get("status")
        return page, []
    page.status_code = result["status"]
    page.response_ms = result["ms"]
    page.bytes = len(result["body"])
    headers = result["headers"]
    page.content_type = headers.get("content-type", "").split(";")[0].strip()
    page.security_headers = {h: headers.get(h, "") for h in SECURITY_HEADERS}
    if "html" not in page.content_type or page.status_code != 200:
        return page, []
    parser = _Parser()
    try:
        parser.feed(result["body"].decode("utf8", "replace"))
    except Exception as exc:
        page.fetch_error = f"parse: {exc}"[:300]
        return page, []
    text = parser.text
    page.title = re.sub(r"\s+", " ", parser.title).strip()[:500]
    page.meta_description = parser.meta_description[:1000]
    page.meta_robots = parser.meta_robots[:100]
    page.canonical = (normalize(parser.canonical, page.final_url) or "")[:1000] if parser.canonical else ""
    page.lang = parser.lang[:16]
    page.h1 = parser.h1[:10]
    page.h2_count = parser.h2_count
    page.word_count = len(text.split())
    page.text_hash = hashlib.md5(text.lower().encode()).hexdigest()
    page.text_sample = text[:3000]
    page.images_total = parser.images_total
    page.images_missing_alt = parser.images_missing_alt
    page.mixed_content = parser.http_resources if page.final_url.startswith("https://") else 0
    page.jsonld_types, page.jsonld_error = _jsonld(parser.jsonld)
    internal, external = set(), set()
    for href in parser.links:
        link = normalize(href, page.final_url)
        if not link or link.startswith(("mailto:", "tel:")):
            continue
        (internal if same_site(link, host) else external).add(link)
    page.internal_links = sorted(internal)[:500]
    page.external_links = sorted(external)[:200]
    return page, [u for u in internal if not SKIP_EXT.search(u)]


def _jsonld(blocks):
    import json

    types = []
    for raw in blocks:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            return types, f"invalid JSON-LD: {exc.msg}"[:200]
        items = data if isinstance(data, list) else [data]
        for item in items:
            if isinstance(item, dict):
                t = item.get("@type")
                types += t if isinstance(t, list) else [t] if t else []
                for g in item.get("@graph", []) if isinstance(item.get("@graph"), list) else []:
                    if isinstance(g, dict) and g.get("@type"):
                        types.append(g["@type"] if isinstance(g["@type"], str) else g["@type"][0])
    return sorted(set(str(t) for t in types)), ""


def _check_externals(urls, log, cap=150):
    """HEAD every unique external link once. Broken outbound links hurt trust."""
    def head(u):
        req = urllib.request.Request(u, method="HEAD", headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return u, resp.status
        except urllib.error.HTTPError as exc:
            return u, exc.code
        except Exception:
            return u, 0

    picked = sorted(urls)[:cap]
    log(f"checking {len(picked)} external links")
    with ThreadPoolExecutor(max_workers=8) as pool:
        return dict(pool.map(head, picked))


def _map_wp(pages, site, log):
    """Attach the WordPress item behind each URL so approved fixes know where to write."""
    import wp

    env = sites.env_for(site)
    by_link = {}
    for base in ("posts", "pages", "solution"):
        try:
            for item in wp.call(f"/{base}?per_page=100&_fields=id,link&status=publish", env=env):
                by_link[normalize(item["link"]).rstrip("/")] = (base, item["id"])
        except RuntimeError:
            pass
    hits = 0
    for page in pages:
        key = normalize(page.final_url or page.url)
        match = by_link.get((key or "").rstrip("/"))
        if match:
            page.wp_base, page.wp_id = match
            hits += 1
    log(f"mapped {hits}/{len(pages)} pages to WordPress items")


def run(site=None, max_pages=300, log=print):
    """Crawl one site into a Crawl + Page rows. Returns the Crawl."""
    env = sites.env_for(site)
    root = env["WEBSITE_LINK"].rstrip("/")
    host = urllib.parse.urlsplit(root).netloc.lower()
    crawl = Crawl.objects.create(site=env["_site_id"])
    log(f"crawl #{crawl.pk}: {root} (max {max_pages} pages)")
    try:
        robots, robots_txt = _robots(root)
        sitemap_url, sitemap = _sitemap_urls(root)
        log(f"sitemap: {sitemap_url or 'none found'} ({len(sitemap)} urls)")
        crawl.sitemap_url, crawl.sitemap_urls, crawl.robots_txt = sitemap_url, sitemap, robots_txt
        crawl.save()

        sitemap_set = {normalize(u) for u in sitemap if normalize(u)}
        seen = {normalize(root + "/")}
        frontier = [(normalize(root + "/"), 0)]
        for u in sorted(sitemap_set):
            if u not in seen:
                seen.add(u)
                frontier.append((u, 1))
        pages = []
        done_urls = set()
        externals = set()
        while frontier and len(pages) < max_pages:
            batch, frontier = frontier[:16], frontier[16:]

            def one(item):
                url, depth = item
                blocked = not robots.can_fetch(USER_AGENT, url)
                result = fetch(url) if not blocked else {"error": "blocked by robots.txt", "final_url": url}
                if result.get("chain") and result.get("final_url") != url and "error" not in result:
                    # A redirecting URL is its own row (status 301/302); the target is a page in
                    # its own right and gets parsed once, under its real URL.
                    hop = Page(url=url, depth=depth, in_sitemap=url in sitemap_set, robots_blocked=blocked,
                               final_url=result["final_url"], redirect_chain=result["chain"],
                               status_code=result["chain"][0]["status"], response_ms=result["ms"])
                    target, links = _page_from(result["final_url"], {**result, "chain": []}, host, depth,
                                               result["final_url"] in sitemap_set, blocked)
                    return [(hop, [result["final_url"]]), (target, links)]
                return [_page_from(url, result, host, depth, url in sitemap_set, blocked)]

            with ThreadPoolExecutor(max_workers=8) as pool:
                for results in pool.map(one, batch):
                    for page, links in results:
                        if page.url in done_urls:
                            continue  # redirect target already crawled directly
                        done_urls.add(page.url)
                        seen.add(page.url)
                        page.crawl = crawl
                        pages.append(page)
                        externals.update(page.external_links)
                        for link in links:
                            if link not in seen and len(seen) < max_pages * 3:
                                seen.add(link)
                                frontier.append((link, page.depth + 1))
            log(f"fetched {len(pages)} pages, {len(frontier)} queued")

        Page.objects.bulk_create(pages, batch_size=200)
        _map_wp(pages, site, log)
        Page.objects.bulk_update(pages, ["wp_base", "wp_id"], batch_size=200)
        crawl.external_checks = _check_externals(externals, log)
        crawl.pages_total = len(pages)
        crawl.status = "done"
    except Exception as exc:
        crawl.status = "failed"
        crawl.note = str(exc)[:500]
        log(f"crawl failed: {exc}")
        raise
    finally:
        crawl.finished_at = timezone.now()
        crawl.save()
    log(f"done: {crawl.pages_total} pages")
    return crawl


def latest(site=None):
    site_id = sites.env_for(site)["_site_id"]
    return Crawl.objects.filter(site=site_id).order_by("-id").first()
