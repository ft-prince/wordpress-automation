"""SQLite store: runs, logs, audit. SQLite until SQLite hurts."""
import json
import os
import sqlite3
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "automation.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id     TEXT NOT NULL,
  status     TEXT NOT NULL,          -- running | success | failed | timeout | killed
  started_at TEXT NOT NULL,
  ended_at   TEXT,
  duration_ms INTEGER,
  exit_code  INTEGER,
  dry_run    INTEGER NOT NULL DEFAULT 0,
  trigger    TEXT NOT NULL DEFAULT 'manual',
  site       TEXT NOT NULL DEFAULT '',
  error      TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_job ON runs(job_id, id DESC);

CREATE TABLE IF NOT EXISTS logs (
  id     INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,
  ts     TEXT NOT NULL,
  stream TEXT NOT NULL,              -- stdout | stderr | system
  line   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_logs_run ON logs(run_id, id);

CREATE TABLE IF NOT EXISTS audit (
  id     INTEGER PRIMARY KEY AUTOINCREMENT,
  ts     TEXT NOT NULL,
  actor  TEXT NOT NULL,
  action TEXT NOT NULL,
  target TEXT NOT NULL,
  before TEXT,
  after  TEXT
);
"""


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init():
    with connect() as conn:
        conn.executescript(SCHEMA)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(runs)")]
        if "site" not in cols:
            conn.execute("ALTER TABLE runs ADD COLUMN site TEXT NOT NULL DEFAULT ''")


def _rows(sql, params=()):
    with connect() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def start_run(job_id, trigger="manual", dry_run=False, site=""):
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO runs (job_id,status,started_at,dry_run,trigger,site) VALUES (?,'running',?,?,?,?)",
            (job_id, now(), int(dry_run), trigger, site or ""),
        )
        return cur.lastrowid


def finish_run(run_id, status, exit_code=None, error=None):
    with connect() as conn:
        started = conn.execute("SELECT started_at FROM runs WHERE id=?", (run_id,)).fetchone()
        duration = None
        if started:
            begin = datetime.fromisoformat(started["started_at"])
            duration = int((datetime.now(timezone.utc) - begin).total_seconds() * 1000)
        conn.execute(
            "UPDATE runs SET status=?,ended_at=?,duration_ms=?,exit_code=?,error=? WHERE id=?",
            (status, now(), duration, exit_code, error, run_id),
        )


def add_log(run_id, line, stream="stdout"):
    with connect() as conn:
        conn.execute(
            "INSERT INTO logs (run_id,ts,stream,line) VALUES (?,?,?,?)", (run_id, now(), stream, line)
        )


def run(run_id):
    rows = _rows("SELECT * FROM runs WHERE id=?", (run_id,))
    return rows[0] if rows else None


def runs(job_id=None, status=None, limit=50, offset=0, site=None):
    where, params = [], []
    if job_id:
        where.append("job_id=?")
        params.append(job_id)
    if status:
        where.append("status=?")
        params.append(status)
    if site:
        where.append("site=?")
        params.append(site)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    params += [limit, offset]
    return _rows(f"SELECT * FROM runs {clause} ORDER BY id DESC LIMIT ? OFFSET ?", params)


def logs(run_id, after_id=0):
    return _rows("SELECT * FROM logs WHERE run_id=? AND id>? ORDER BY id", (run_id, after_id))


def last_run(job_id):
    rows = _rows("SELECT * FROM runs WHERE job_id=? ORDER BY id DESC LIMIT 1", (job_id,))
    return rows[0] if rows else None


def recent_durations(job_id, limit=30):
    rows = _rows(
        "SELECT duration_ms FROM runs WHERE job_id=? AND duration_ms IS NOT NULL "
        "ORDER BY id DESC LIMIT ?",
        (job_id, limit),
    )
    return [r["duration_ms"] for r in reversed(rows)]


def audit(limit=100):
    return _rows("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,))


def add_audit(actor, action, target, before=None, after=None):
    with connect() as conn:
        conn.execute(
            "INSERT INTO audit (ts,actor,action,target,before,after) VALUES (?,?,?,?,?,?)",
            (
                now(),
                actor,
                action,
                target,
                json.dumps(before) if before is not None else None,
                json.dumps(after) if after is not None else None,
            ),
        )


def metrics(site=None):
    scope = " AND site=?" if site else ""
    sp = (site,) if site else ()
    with connect() as conn:
        def scalar(sql, params=()):
            return conn.execute(sql, params).fetchone()[0] or 0

        total = scalar(f"SELECT COUNT(*) FROM runs WHERE 1=1{scope}", sp)
        done = scalar(f"SELECT COUNT(*) FROM runs WHERE status IN ('success','failed','timeout'){scope}", sp)
        ok = scalar(f"SELECT COUNT(*) FROM runs WHERE status='success'{scope}", sp)
        return {
            "runs_total": total,
            "running_now": scalar(f"SELECT COUNT(*) FROM runs WHERE status='running'{scope}", sp),
            "failed_24h": scalar(
                f"SELECT COUNT(*) FROM runs WHERE status IN ('failed','timeout') "
                f"AND started_at > datetime('now','-1 day'){scope}", sp),
            "failed_7d": scalar(
                f"SELECT COUNT(*) FROM runs WHERE status IN ('failed','timeout') "
                f"AND started_at > datetime('now','-7 day'){scope}", sp),
            "success_rate": round(ok / done * 100) if done else None,
            "avg_duration_ms": round(scalar(f"SELECT AVG(duration_ms) FROM runs WHERE status='success'{scope}", sp)),
        }


def heatmap(days=7, site=None):
    """One cell per job per day: worst outcome that day wins."""
    scope = " AND site=?" if site else ""
    params = [f"-{days} day"] + ([site] if site else [])
    return _rows(
        "SELECT job_id, date(started_at) AS day, "
        "  SUM(status='success') AS ok, "
        "  SUM(status IN ('failed','timeout')) AS bad "
        f"FROM runs WHERE started_at > datetime('now', ?){scope} "
        "GROUP BY job_id, day ORDER BY day",
        params,
    )


init()
