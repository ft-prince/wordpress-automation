"""Automations: registry entries, runs, logs, metrics."""
from ninja import Router, Schema
from ninja.errors import HttpError

from core import registry, runner, scheduler, sites, store

router = Router()


class Patch(Schema):
    name: str | None = None
    description: str | None = None
    schedule: str | None = None
    enabled: bool | None = None
    timeout_seconds: int | None = None
    args: dict | None = None
    tags: list[str] | None = None
    alert_on_failure: bool | None = None


class Source(Schema):
    body: str


class RunRequest(Schema):
    dry_run: bool = False


class JobCreate(Schema):
    id: str
    name: str
    description: str = ""
    runtime: str = "python"
    entrypoint: str
    schedule: str = "manual"
    timeout_seconds: int = 300
    tags: list[str] = []


def job_site(job):
    return (job.get("args") or {}).get("site") or sites.default_id() or ""


def decorate(job):
    """Registry entry + live state. The registry stays the source of truth."""
    last = store.last_run(job["id"])
    current_step = None
    if last and last["status"] == "running":
        lines = store.logs(last["id"])
        if lines:
            current_step = lines[-1]["line"][:120]
    return {
        **job,
        "target_site": job_site(job),
        "last_run": last,
        "next_run": scheduler.next_run(job["id"]),
        "status": (last or {}).get("status", "never"),
        "current_step": current_step,
    }


@router.get("/jobs")
def list_jobs(request, site: str | None = None):
    jobs = [decorate(j) for j in registry.all_jobs()]
    if site:
        jobs = [j for j in jobs if j["target_site"] == site]
    return jobs


@router.post("/jobs")
def create_job(request, body: JobCreate):
    job = registry.create(body.dict())
    scheduler.reload()
    return decorate(job)


@router.get("/jobs/{job_id}")
def job_detail(request, job_id: str):
    job = registry.get(job_id)
    return {
        **decorate(job),
        "yaml": registry.raw(job_id),
        "source": registry.source(job_id),
        "durations": store.recent_durations(job_id),
        "runs": store.runs(job_id, limit=20),
    }


@router.patch("/jobs/{job_id}")
def patch_job(request, job_id: str, patch: Patch):
    changes = {k: v for k, v in patch.dict().items() if v is not None}
    if not changes:
        raise HttpError(400, "nothing to change")
    job = registry.update(job_id, changes)
    scheduler.reload()
    return decorate(job)


@router.delete("/jobs/{job_id}")
def delete_job(request, job_id: str):
    registry.delete(job_id)
    scheduler.reload()
    return {"deleted": True}


@router.put("/jobs/{job_id}/source")
def put_source(request, job_id: str, payload: Source):
    try:
        registry.save_source(job_id, payload.body)
    except SyntaxError as exc:
        raise HttpError(400, f"syntax error line {exc.lineno}: {exc.msg}")
    return {"saved": True}


@router.post("/jobs/{job_id}/run")
def run_now(request, job_id: str, body: RunRequest = None, site: str | None = None):
    registry.get(job_id)
    last = store.last_run(job_id)
    if last and last["status"] == "running":
        raise HttpError(409, "this automation is already running, check Logs")
    dry = bool(body and body.dry_run)
    extra = {"site": site} if site else None
    runner.execute_async(job_id, trigger="manual", dry_run=dry, extra_args=extra)
    return {"started": True, "dry_run": dry, "site": site}


@router.post("/jobs/{job_id}/duplicate")
def duplicate_job(request, job_id: str):
    job = registry.duplicate(job_id)
    scheduler.reload()
    return decorate(job)


@router.get("/runs")
def list_runs(request, job: str | None = None, status: str | None = None, limit: int = 50,
              offset: int = 0, site: str | None = None):
    return store.runs(job_id=job, status=status, limit=min(limit, 200), offset=offset, site=site)


@router.get("/runs/{run_id}/logs")
def run_logs(request, run_id: int, after: int = 0):
    """Log lines after cursor `after`, plus whether the run is still going.
    The dashboard polls this - no WebSocket, no message bus."""
    run = store.run(run_id)
    if not run:
        raise HttpError(404, "no such run")
    return {"lines": store.logs(run_id, after_id=after), "status": run["status"],
            "done": run["status"] != "running"}


@router.post("/runs/{run_id}/retry")
def retry_run(request, run_id: int):
    """Retry = run the same job again, linked in the audit trail."""
    run = store.run(run_id)
    if not run:
        raise HttpError(404, "no such run")
    if run["status"] == "running":
        raise HttpError(400, "run is still in progress")
    runner.execute_async(run["job_id"], trigger=f"retry-of-{run_id}", dry_run=bool(run["dry_run"]))
    store.add_audit("dashboard", "retry", f"run:{run_id}")
    return {"started": True, "job_id": run["job_id"]}


@router.post("/runs/{run_id}/stop")
def stop_run(request, run_id: int):
    if not runner.stop(run_id):
        raise HttpError(404, "run not active")
    return {"stopped": True}


@router.get("/metrics")
def metrics(request, site: str | None = None):
    jobs = [j for j in registry.all_jobs() if not site or job_site(j) == site]
    return {
        **store.metrics(site=site),
        "jobs_total": len(jobs),
        "jobs_enabled": sum(1 for j in jobs if j.get("enabled", True)),
        "heatmap": store.heatmap(site=site),
    }
