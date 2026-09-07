"""Runs, logs, audit on the Django ORM. Function signatures are unchanged from the
SQLModel version; rows come back as plain dicts with ISO timestamps so every caller
(runner, API, alerts) keeps working untouched."""
from datetime import datetime, timedelta, timezone

from django.db.models import Avg, Count, Q
from django.db.models.functions import Substr
from django.forms.models import model_to_dict
from django.utils import timezone as dj_tz

from core.models import AuditEntry, LogLine, Run

FINISHED = ("success", "failed", "timeout")
BAD = ("failed", "timeout")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init():
    """Tables are managed by migrations now; kept so old call sites don't break."""


def _row(obj):
    if obj is None:
        return None
    data = model_to_dict(obj)
    data["id"] = obj.pk
    for key, value in data.items():
        if isinstance(value, datetime):
            data[key] = value.isoformat(timespec="seconds")
    return data


def start_run(job_id, trigger="manual", dry_run=False, site=""):
    return Run.objects.create(job_id=job_id, status="running", dry_run=int(dry_run),
                              trigger=trigger, site=site or "").pk


def finish_run(run_id, status, exit_code=None, error=None):
    run_row = Run.objects.filter(pk=run_id).first()
    if not run_row:
        return
    ended = dj_tz.now()
    run_row.status = status
    run_row.ended_at = ended
    run_row.duration_ms = int((ended - run_row.started_at).total_seconds() * 1000)
    run_row.exit_code = exit_code
    run_row.error = error
    run_row.save()


def add_log(run_id, line, stream="stdout"):
    LogLine.objects.create(run_id=run_id, stream=stream, line=line)


def run(run_id):
    return _row(Run.objects.filter(pk=run_id).first())


def runs(job_id=None, status=None, limit=50, offset=0, site=None):
    query = Run.objects.all()
    if job_id:
        query = query.filter(job_id=job_id)
    if status:
        query = query.filter(status=status)
    if site:
        query = query.filter(site=site)
    return [_row(r) for r in query.order_by("-id")[offset:offset + limit]]


def logs(run_id, after_id=0):
    query = LogLine.objects.filter(run_id=run_id, id__gt=after_id).order_by("id")
    return [{**_row(l), "run_id": l.run_id} for l in query]


def last_run(job_id):
    return _row(Run.objects.filter(job_id=job_id).order_by("-id").first())


def recent_durations(job_id, limit=30):
    rows = (Run.objects.filter(job_id=job_id, duration_ms__isnull=False)
            .order_by("-id").values_list("duration_ms", flat=True)[:limit])
    return list(reversed(list(rows)))


def audit(limit=100):
    return [_row(a) for a in AuditEntry.objects.order_by("-id")[:limit]]


def add_audit(actor, action, target, before=None, after=None):
    AuditEntry.objects.create(actor=actor, action=action, target=target,
                              before=before, after=after)


def metrics(site=None):
    base = Run.objects.filter(site=site) if site else Run.objects.all()
    day_ago = dj_tz.now() - timedelta(days=1)
    week_ago = dj_tz.now() - timedelta(days=7)
    agg = base.aggregate(
        total=Count("id"),
        done=Count("id", filter=Q(status__in=FINISHED)),
        ok=Count("id", filter=Q(status="success")),
        running=Count("id", filter=Q(status="running")),
        failed_24h=Count("id", filter=Q(status__in=BAD, started_at__gt=day_ago)),
        failed_7d=Count("id", filter=Q(status__in=BAD, started_at__gt=week_ago)),
        avg=Avg("duration_ms", filter=Q(status="success")),
    )
    return {
        "runs_total": agg["total"],
        "running_now": agg["running"],
        "failed_24h": agg["failed_24h"],
        "failed_7d": agg["failed_7d"],
        "success_rate": round(agg["ok"] / agg["done"] * 100) if agg["done"] else None,
        "avg_duration_ms": round(agg["avg"] or 0),
    }


def heatmap(days=7, site=None):
    """One cell per job per day: worst outcome that day wins."""
    since = dj_tz.now() - timedelta(days=days)
    query = Run.objects.filter(started_at__gt=since)
    if site:
        query = query.filter(site=site)
    rows = (query.annotate(day=Substr("started_at", 1, 10))
            .values("job_id", "day")
            .annotate(ok=Count("id", filter=Q(status="success")),
                      bad=Count("id", filter=Q(status__in=BAD)))
            .order_by("day"))
    return list(rows)
