"""Every table PressPilot owns. Timestamps are aware datetimes (USE_TZ)."""
from django.conf import settings
from django.db import models
from django.utils import timezone


class Run(models.Model):
    STATUSES = ("running", "success", "failed", "timeout", "killed")

    job_id = models.CharField(max_length=64, db_index=True)
    status = models.CharField(max_length=16)
    started_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)
    duration_ms = models.IntegerField(null=True, blank=True)
    exit_code = models.IntegerField(null=True, blank=True)
    dry_run = models.IntegerField(default=0)
    trigger = models.CharField(max_length=64, default="manual")
    site = models.CharField(max_length=48, default="", blank=True)
    error = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "runs"


class LogLine(models.Model):
    run = models.ForeignKey(Run, on_delete=models.CASCADE, related_name="lines")
    ts = models.DateTimeField(default=timezone.now)
    stream = models.CharField(max_length=8, default="stdout")  # stdout | stderr | system
    line = models.TextField()

    class Meta:
        db_table = "logs"


class AuditEntry(models.Model):
    ts = models.DateTimeField(default=timezone.now)
    actor = models.CharField(max_length=64)
    action = models.CharField(max_length=64)
    target = models.CharField(max_length=255)
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = "audit"


class Topic(models.Model):
    STATUSES = ("suggested", "approved", "rejected", "writing", "written")

    title = models.CharField(max_length=200)
    source = models.CharField(max_length=16, default="manual")
    category = models.CharField(max_length=60, default="", blank=True)
    relevance = models.IntegerField(default=50)
    why = models.CharField(max_length=300, default="", blank=True)
    site = models.CharField(max_length=48, default="", blank=True)
    status = models.CharField(max_length=12, default="suggested")
    position = models.IntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)
    post_id = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = "topics"


class ApiToken(models.Model):
    """Dashboard session token. Survives restarts, expires after a week."""
    key = models.CharField(max_length=64, unique=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()


class SeoAudit(models.Model):
    """Saved content audit (WP items) per site - replaces seo_audits.json."""
    site = models.CharField(max_length=48, unique=True)
    generated_at = models.DateTimeField(default=timezone.now)
    data = models.JSONField(default=dict)


class Crawl(models.Model):
    STATUSES = ("running", "done", "failed")

    site = models.CharField(max_length=48, db_index=True)
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=12, default="running")
    pages_total = models.IntegerField(default=0)
    sitemap_url = models.CharField(max_length=500, default="", blank=True)
    sitemap_urls = models.JSONField(default=list)
    robots_txt = models.TextField(default="", blank=True)
    external_checks = models.JSONField(default=dict)  # url -> status code
    note = models.TextField(default="", blank=True)


class Page(models.Model):
    """One fetched URL in a crawl. Lists live in JSON columns - SQLite has no arrays."""
    crawl = models.ForeignKey(Crawl, on_delete=models.CASCADE, related_name="pages")
    url = models.CharField(max_length=1000)
    final_url = models.CharField(max_length=1000, default="", blank=True)
    status_code = models.IntegerField(null=True, blank=True)
    redirect_chain = models.JSONField(default=list)
    content_type = models.CharField(max_length=100, default="", blank=True)
    response_ms = models.IntegerField(null=True, blank=True)
    bytes = models.IntegerField(default=0)
    depth = models.IntegerField(default=0)
    in_sitemap = models.BooleanField(default=False)
    robots_blocked = models.BooleanField(default=False)
    fetch_error = models.CharField(max_length=300, default="", blank=True)

    title = models.CharField(max_length=500, default="", blank=True)
    meta_description = models.CharField(max_length=1000, default="", blank=True)
    meta_robots = models.CharField(max_length=100, default="", blank=True)
    canonical = models.CharField(max_length=1000, default="", blank=True)
    lang = models.CharField(max_length=16, default="", blank=True)
    h1 = models.JSONField(default=list)
    h2_count = models.IntegerField(default=0)
    word_count = models.IntegerField(default=0)
    text_hash = models.CharField(max_length=32, default="", blank=True)
    text_sample = models.TextField(default="", blank=True)
    internal_links = models.JSONField(default=list)
    external_links = models.JSONField(default=list)
    images_total = models.IntegerField(default=0)
    images_missing_alt = models.IntegerField(default=0)
    jsonld_types = models.JSONField(default=list)
    jsonld_error = models.CharField(max_length=200, default="", blank=True)
    mixed_content = models.IntegerField(default=0)
    security_headers = models.JSONField(default=dict)

    # Which WordPress item renders this URL, so approved fixes know where to write.
    wp_base = models.CharField(max_length=32, default="", blank=True)
    wp_id = models.IntegerField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["crawl", "url"])]

    @property
    def is_html(self):
        return "html" in (self.content_type or "")

    @property
    def indexable(self):
        return (self.status_code == 200 and self.is_html and not self.robots_blocked
                and "noindex" not in (self.meta_robots or "").lower())


class BusinessProfile(models.Model):
    """What the business actually sells and to whom. Every SEO decision reads this first."""
    site = models.CharField(max_length=48, unique=True)
    name = models.CharField(max_length=120, default="", blank=True)
    description = models.TextField(default="", blank=True)
    products = models.JSONField(default=list)      # ["...", ...]
    services = models.JSONField(default=list)
    industries = models.JSONField(default=list)
    audience = models.TextField(default="", blank=True)  # ICP in plain words
    locations = models.JSONField(default=list)
    markets = models.JSONField(default=list)       # countries / languages
    priorities = models.JSONField(default=list)    # [{"topic": "...", "weight": 1-5}]
    brand_voice = models.TextField(default="", blank=True)
    facts = models.JSONField(default=list)         # approved claims the writer may use
    competitors = models.JSONField(default=list)
    updated_at = models.DateTimeField(auto_now=True)


class Change(models.Model):
    """Every proposed write to WordPress. Nothing reaches the site without status=applied,
    and `before` is kept so any applied change can be rolled back with one call."""
    STATUSES = ("proposed", "applied", "rejected", "rolled_back", "failed")

    site = models.CharField(max_length=48, db_index=True)
    kind = models.CharField(max_length=32)          # title | meta | h1 | content | create-post | ...
    wp_base = models.CharField(max_length=32, default="", blank=True)
    wp_id = models.IntegerField(null=True, blank=True)
    field = models.CharField(max_length=32, default="", blank=True)
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
    reason = models.TextField(default="", blank=True)
    source = models.CharField(max_length=32, default="ai")  # ai | human | rule
    status = models.CharField(max_length=12, default="proposed", db_index=True)
    created_at = models.DateTimeField(default=timezone.now)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.CharField(max_length=64, default="", blank=True)
    error = models.TextField(default="", blank=True)


class Brief(models.Model):
    """SEO brief -> AI draft -> QA -> human approval -> WordPress draft. One row, one lifecycle."""
    STATUSES = ("brief", "drafted", "qa", "approved", "published", "rejected")

    site = models.CharField(max_length=48, db_index=True)
    topic = models.ForeignKey(Topic, null=True, blank=True, on_delete=models.SET_NULL)
    title = models.CharField(max_length=200)
    primary_keyword = models.CharField(max_length=120, default="", blank=True)
    secondary_keywords = models.JSONField(default=list)
    intent = models.CharField(max_length=24, default="informational")
    content_type = models.CharField(max_length=24, default="blog")
    audience = models.TextField(default="", blank=True)
    outline = models.JSONField(default=list)        # [{"h2": "...", "h3": [...], "notes": "..."}]
    entities = models.JSONField(default=list)
    faqs = models.JSONField(default=list)
    internal_links = models.JSONField(default=list)  # [{"title","url"}]
    cta = models.TextField(default="", blank=True)
    word_target = models.IntegerField(default=900)
    custom_instructions = models.TextField(default="", blank=True)
    prompt_version = models.CharField(max_length=16, default="", blank=True)
    draft_title = models.CharField(max_length=200, default="", blank=True)
    draft_meta = models.CharField(max_length=300, default="", blank=True)
    draft_html = models.TextField(default="", blank=True)
    qa = models.JSONField(default=dict)
    status = models.CharField(max_length=12, default="brief", db_index=True)
    post_id = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)


class Cluster(models.Model):
    """A topic: keywords that one page should answer. Maps to an existing URL, a page to
    improve, or a page that does not exist yet (content gap)."""
    ACTIONS = ("existing", "improve", "new", "ignore")
    ROLES = ("pillar", "cluster", "supporting")

    site = models.CharField(max_length=48, db_index=True)
    name = models.CharField(max_length=160)
    parent_topic = models.CharField(max_length=160, default="", blank=True)
    intent = models.CharField(max_length=24, default="informational")
    role = models.CharField(max_length=12, default="cluster")
    action = models.CharField(max_length=12, default="")
    target_url = models.CharField(max_length=1000, default="", blank=True)
    target_wp_base = models.CharField(max_length=32, default="", blank=True)
    target_wp_id = models.IntegerField(null=True, blank=True)
    reason = models.TextField(default="", blank=True)
    priority = models.IntegerField(default=50)      # business priority x opportunity, 0-100
    approved = models.BooleanField(default=False)   # SEO user signed off on the mapping
    created_at = models.DateTimeField(default=timezone.now)


class Keyword(models.Model):
    SOURCES = ("seed", "longtail", "question", "crawl", "topic", "brief", "manual")

    site = models.CharField(max_length=48, db_index=True)
    text = models.CharField(max_length=160)
    source = models.CharField(max_length=12, default="manual")
    intent = models.CharField(max_length=24, default="", blank=True)
    relevance = models.IntegerField(default=50)     # business relevance 0-100
    commercial = models.IntegerField(default=0)     # commercial value 0-100
    cluster = models.ForeignKey(Cluster, null=True, blank=True, on_delete=models.SET_NULL, related_name="keywords")
    is_primary = models.BooleanField(default=False)
    found_on = models.JSONField(default=list)       # crawled URLs whose title/h1 already carry it
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = [("site", "text")]


class GscRow(models.Model):
    """One Search Console row: date x query x page. Source + freshness live on the sync."""
    site = models.CharField(max_length=48, db_index=True)
    date = models.DateField()
    query = models.CharField(max_length=300)
    page = models.CharField(max_length=1000)
    clicks = models.IntegerField(default=0)
    impressions = models.IntegerField(default=0)
    ctr = models.FloatField(default=0)
    position = models.FloatField(default=0)

    class Meta:
        indexes = [models.Index(fields=["site", "date"]), models.Index(fields=["site", "query"]),
                   models.Index(fields=["site", "page"])]


class Ga4Row(models.Model):
    """One GA4 row: date x landing page x channel."""
    site = models.CharField(max_length=48, db_index=True)
    date = models.DateField()
    landing_page = models.CharField(max_length=1000)
    channel = models.CharField(max_length=64, default="")
    sessions = models.IntegerField(default=0)
    users = models.IntegerField(default=0)
    conversions = models.FloatField(default=0)

    class Meta:
        indexes = [models.Index(fields=["site", "date"]), models.Index(fields=["site", "landing_page"])]


class Sync(models.Model):
    """Data provenance: which source, when, how many rows, what went wrong."""
    site = models.CharField(max_length=48, db_index=True)
    source = models.CharField(max_length=16)  # gsc | ga4
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    rows = models.IntegerField(default=0)
    date_from = models.DateField(null=True, blank=True)
    date_to = models.DateField(null=True, blank=True)
    error = models.TextField(default="", blank=True)
