"""Executes a job: captures stdout/stderr, enforces timeout, records everything."""
import os
import subprocess
import sys
import threading

from core import registry, store

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHON = os.path.join(ROOT, ".venv", "bin", "python")
DEFAULT_TIMEOUT = 300

_procs = {}   # run_id -> Popen, so a run can be killed from the dashboard
_lock = threading.Lock()


def _command(job, dry_run, extra_args=None):
    entry = os.path.join(ROOT, job["entrypoint"])
    interpreter = {
        "python": [PYTHON if os.path.exists(PYTHON) else sys.executable],
        "node": ["node"],
        "bash": ["bash"],
    }[job["runtime"]]

    cmd = interpreter + [entry]
    merged = {**(job.get("args") or {}), **(extra_args or {})}
    for key, value in merged.items():
        cmd += [f"--{key}", str(value)]
    if dry_run:
        cmd.append("--dry-run")
    return cmd


def execute(job_id, trigger="manual", dry_run=False, extra_args=None):
    """Run a job to completion. Returns the finished run row. Never raises to the caller."""
    job = registry.get(job_id)
    run_id = store.start_run(job_id, trigger=trigger, dry_run=dry_run)
    timeout = job.get("timeout_seconds") or DEFAULT_TIMEOUT
    cmd = _command(job, dry_run, extra_args)
    store.add_log(run_id, f"$ {' '.join(cmd)}", "system")

    try:
        proc = subprocess.Popen(
            cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
    except Exception as exc:
        store.add_log(run_id, f"spawn failed: {exc}", "stderr")
        store.finish_run(run_id, "failed", error=str(exc))
        return store.run(run_id)

    with _lock:
        _procs[run_id] = proc

    timed_out = threading.Event()

    def kill():
        timed_out.set()
        proc.kill()

    timer = threading.Timer(timeout, kill)
    timer.start()
    try:
        for line in proc.stdout:
            store.add_log(run_id, line.rstrip("\n"))
        proc.wait()
    finally:
        timer.cancel()
        with _lock:
            _procs.pop(run_id, None)

    if timed_out.is_set():
        store.add_log(run_id, f"killed after {timeout}s timeout", "system")
        store.finish_run(run_id, "timeout", exit_code=proc.returncode, error="timeout")
    elif proc.returncode == 0:
        store.finish_run(run_id, "success", exit_code=0)
    else:
        store.finish_run(run_id, "failed", exit_code=proc.returncode,
                         error=f"exit code {proc.returncode}")
    return store.run(run_id)


def execute_async(job_id, trigger="manual", dry_run=False, extra_args=None):
    """Anything over ~2 minutes must not block a request."""
    run_id_box = {}
    done = threading.Event()

    def target():
        result = execute(job_id, trigger, dry_run, extra_args)
        run_id_box["run"] = result
        done.set()

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return thread


def stop(run_id):
    with _lock:
        proc = _procs.get(run_id)
    if not proc:
        return False
    proc.kill()
    store.add_log(run_id, "killed from dashboard", "system")
    store.finish_run(run_id, "killed", error="killed by user")
    return True
