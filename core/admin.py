from django.contrib import admin

from core.models import AuditEntry, Crawl, Page, Run, SeoAudit, Topic


@admin.register(Run)
class RunAdmin(admin.ModelAdmin):
    list_display = ("id", "job_id", "status", "site", "started_at", "duration_ms")
    list_filter = ("status", "job_id", "site")


@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "status", "site", "relevance", "position")
    list_filter = ("status", "site")


@admin.register(AuditEntry)
class AuditAdmin(admin.ModelAdmin):
    list_display = ("ts", "actor", "action", "target")


@admin.register(Crawl)
class CrawlAdmin(admin.ModelAdmin):
    list_display = ("id", "site", "status", "pages_total", "started_at", "finished_at")


@admin.register(Page)
class PageAdmin(admin.ModelAdmin):
    list_display = ("url", "status_code", "title", "word_count", "crawl")
    search_fields = ("url", "title")


admin.site.register(SeoAudit)
