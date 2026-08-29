"""APScheduler owns all cron. No OS crontab."""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from core import registry, runner

_scheduler = BackgroundScheduler(timezone="UTC")
MANUAL = ("manual", "", None, "@manual")


def _trigger(schedule):
    """Cron string -> trigger. Returns None for manual-only jobs."""
    if schedule in MANUAL or str(schedule).startswith("@on_"):
        return None
    return CronTrigger.from_crontab(schedule, timezone="UTC")


def reload():
    """Rebuild every scheduled job from the registry. Called on boot and after any edit."""
    _scheduler.remove_all_jobs()
    loaded = 0
    for job in registry.all_jobs():
        if not job.get("enabled", True):
            continue
        trigger = _trigger(job.get("schedule"))
        if trigger is None:
            continue
        _scheduler.add_job(
            runner.execute,
            trigger=trigger,
            args=[job["id"]],
            kwargs={"trigger": "schedule"},
            id=job["id"],
            replace_existing=True,
            max_instances=1,          # never let a slow run overlap itself
            coalesce=True,
        )
        loaded += 1
    return loaded


def next_run(job_id):
    job = _scheduler.get_job(job_id)
    return job.next_run_time.isoformat() if job and job.next_run_time else None


def start():
    if not _scheduler.running:
        _scheduler.start()
    return reload()


def shutdown():
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
