"""Registry = one YAML per automation, the single source of truth."""
import os
import re
import shutil

import yaml

from core import store

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGISTRY_DIR = os.path.join(ROOT, "registry")
BACKUP_DIR = os.path.join(ROOT, ".backups")

REQUIRED = ("id", "name", "runtime", "entrypoint", "schedule")
EDITABLE = ("name", "description", "schedule", "enabled", "timeout_seconds", "retries", "args",
            "env", "tags", "alert_on_failure")
SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def _path(job_id):
    """Reject anything that isn't a plain slug — this value reaches the filesystem."""
    if not SAFE_ID.match(job_id or ""):
        raise ValueError(f"invalid job id: {job_id!r}")
    return os.path.join(REGISTRY_DIR, f"{job_id}.yaml")


def validate(job):
    missing = [k for k in REQUIRED if not job.get(k)]
    if missing:
        raise ValueError(f"registry entry missing: {', '.join(missing)}")
    if not SAFE_ID.match(job["id"]):
        raise ValueError(f"invalid job id: {job['id']!r}")
    if job["runtime"] not in ("python", "bash", "node"):
        raise ValueError(f"unsupported runtime: {job['runtime']}")
    entry = os.path.normpath(os.path.join(ROOT, job["entrypoint"]))
    if not entry.startswith(ROOT + os.sep):
        raise ValueError("entrypoint must stay inside the repo")
    if not os.path.exists(entry):
        raise ValueError(f"entrypoint not found: {job['entrypoint']}")
    return job


def all_jobs():
    os.makedirs(REGISTRY_DIR, exist_ok=True)
    jobs = []
    for name in sorted(os.listdir(REGISTRY_DIR)):
        if name.endswith((".yaml", ".yml")):
            with open(os.path.join(REGISTRY_DIR, name)) as fh:
                data = yaml.safe_load(fh)
            if data:
                jobs.append(data)
    return jobs


def get(job_id):
    path = _path(job_id)
    if not os.path.exists(path):
        raise KeyError(job_id)
    with open(path) as fh:
        return yaml.safe_load(fh)


def raw(job_id):
    with open(_path(job_id)) as fh:
        return fh.read()


def _backup(path):
    os.makedirs(BACKUP_DIR, exist_ok=True)
    if os.path.exists(path):
        stamp = store.now().replace(":", "-")
        shutil.copy2(path, os.path.join(BACKUP_DIR, f"{os.path.basename(path)}.{stamp}"))


def update(job_id, patch, actor="dashboard"):
    """validate -> backup -> apply -> audit. Only EDITABLE fields move."""
    before = get(job_id)
    rejected = [k for k in patch if k not in EDITABLE]
    if rejected:
        raise ValueError(f"not editable: {', '.join(rejected)}")

    after = {**before, **patch}
    validate(after)

    path = _path(job_id)
    _backup(path)
    with open(path, "w") as fh:
        yaml.safe_dump(after, fh, sort_keys=False, allow_unicode=True)

    changed = {k: v for k, v in patch.items() if before.get(k) != v}
    store.add_audit(actor, "update", job_id,
                    {k: before.get(k) for k in changed}, changed)
    return after


def create(entry, actor="dashboard"):
    """New registry entry. Fills safe defaults, refuses to overwrite."""
    entry = {
        "enabled": True, "timeout_seconds": 300,
        "retries": {"count": 1, "backoff_seconds": 60},
        "args": {}, "env": [], "tags": [], "alert_on_failure": True,
        **entry,
    }
    validate(entry)
    path = _path(entry["id"])
    if os.path.exists(path):
        raise ValueError(f"job '{entry['id']}' already exists")
    os.makedirs(REGISTRY_DIR, exist_ok=True)
    with open(path, "w") as fh:
        yaml.safe_dump(entry, fh, sort_keys=False, allow_unicode=True)
    store.add_audit(actor, "create", entry["id"], None, {"name": entry["name"]})
    return entry


def duplicate(job_id, actor="dashboard"):
    src = get(job_id)
    for n in range(2, 100):
        new_id = f"{job_id}-copy{n if n > 2 else ''}"
        if not os.path.exists(_path(new_id)):
            break
    copy = {**src, "id": new_id, "name": f"{src['name']} (copy)", "enabled": False}
    return create(copy, actor)


def delete(job_id, actor="dashboard"):
    job = get(job_id)   # raises KeyError if absent
    path = _path(job_id)
    _backup(path)
    os.remove(path)
    store.add_audit(actor, "delete", job_id, {"name": job["name"]}, None)
    return True


def source(job_id):
    job = get(job_id)
    path = os.path.join(ROOT, job["entrypoint"])
    with open(path) as fh:
        return fh.read()


def save_source(job_id, body, actor="dashboard"):
    """Syntax-check Python before writing. A broken script must never reach disk."""
    job = get(job_id)
    path = os.path.normpath(os.path.join(ROOT, job["entrypoint"]))
    if not path.startswith(ROOT + os.sep):
        raise ValueError("entrypoint escapes the repo")
    if job["runtime"] == "python":
        compile(body, path, "exec")  # SyntaxError propagates to the caller

    _backup(path)
    with open(path, "w") as fh:
        fh.write(body)
    store.add_audit(actor, "edit-source", job_id, None, {"bytes": len(body)})
    return True
