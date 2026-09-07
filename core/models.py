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
