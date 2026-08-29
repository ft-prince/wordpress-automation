"""SQLModel store: runs, logs, audit. Declarative models, ORM queries, same SQLite file.
Public function signatures are unchanged from the raw-sqlite3 version — callers never know.
topics.py still speaks raw SQL through connect(); migrate it here when it next changes."""
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, event, func, text
from sqlmodel import Field, Session, SQLModel, create_engine, select

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "automation.db")

FINISHED = ("success", "failed", "timeout")
BAD = ("failed", "timeout")


class Run(SQLModel, table=True):
    __tablename__ = "runs"
    id: int | None = Field(default=None, primary_key=True)
    job_id: str = Field(index=True)
    status: str  # running | success | failed | timeout | killed
    started_at: str
    ended_at: str | None = None
    duration_ms: int | None = None
    exit_code: int | None = None
    dry_run: int = 0
    trigger: str = "manual"
    site: str = ""
    error: str | None = None


class LogLine(SQLModel, table=True):
    __tablename__ = "logs"
    id: int | None = Field(default=None, primary_key=True)
    run_id: int = Field(index=True)
    ts: str
    stream: str = "stdout"  # stdout | stderr | system
    line: str


class AuditEntry(SQLModel, table=True):
    __tablename__ = "audit"
    id: int | None = Field(default=None, primary_key=True)
    ts: str
    actor: str
    action: str
    target: str
    before: str | None = None
    after: str | None = None


engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"timeout": 10, "check_same_thread": False},
)


@event.listens_for(engine, "connect")
def _wal(dbapi_conn, _record):
    dbapi_conn.execute("PRAGMA journal_mode=WAL")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect():
    """Raw sqlite3 handle for the modules not yet on the ORM (topics.py)."""
    conn = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init():
    SQLModel.metadata.create_all(engine)


def _dump(obj):
    return obj.model_dump() if obj else None


def start_run(job_id, trigger="manual", dry_run=False, site=""):
    with Session(engine) as s:
        run_row = Run(job_id=job_id, status="running", started_at=now(),
                      dry_run=int(dry_run), trigger=trigger, site=site or "")
        s.add(run_row)
        s.commit()
        return run_row.id


def finish_run(run_id, status, exit_code=None, error=None):
    with Session(engine) as s:
        run_row = s.get(Run, run_id)
        if not run_row:
            return
        begin = datetime.fromisoformat(run_row.started_at)
        run_row.status = status
        run_row.ended_at = now()
        run_row.duration_ms = int((datetime.now(timezone.utc) - begin).total_seconds() * 1000)
        run_row.exit_code = exit_code
        run_row.error = error
        s.add(run_row)
        s.commit()


def add_log(run_id, line, stream="stdout"):
    with Session(engine) as s:
        s.add(LogLine(run_id=run_id, ts=now(), stream=stream, line=line))
        s.commit()


def run(run_id):
    with Session(engine) as s:
        return _dump(s.get(Run, run_id))


def runs(job_id=None, status=None, limit=50, offset=0, site=None):
    query = select(Run)
    if job_id:
        query = query.where(Run.job_id == job_id)
    if status:
        query = query.where(Run.status == status)
    if site:
        query = query.where(Run.site == site)
    query = query.order_by(Run.id.desc()).limit(limit).offset(offset)
    with Session(engine) as s:
        return [r.model_dump() for r in s.exec(query)]


def logs(run_id, after_id=0):
    query = (select(LogLine).where(LogLine.run_id == run_id, LogLine.id > after_id)
             .order_by(LogLine.id))
    with Session(engine) as s:
        return [l.model_dump() for l in s.exec(query)]


def last_run(job_id):
    query = select(Run).where(Run.job_id == job_id).order_by(Run.id.desc()).limit(1)
    with Session(engine) as s:
        return _dump(s.exec(query).first())


def recent_durations(job_id, limit=30):
    query = (select(Run.duration_ms)
             .where(Run.job_id == job_id, Run.duration_ms.is_not(None))
             .order_by(Run.id.desc()).limit(limit))
    with Session(engine) as s:
        return list(reversed(s.exec(query).all()))


def audit(limit=100):
    query = select(AuditEntry).order_by(AuditEntry.id.desc()).limit(limit)
    with Session(engine) as s:
        return [a.model_dump() for a in s.exec(query)]


def add_audit(actor, action, target, before=None, after=None):
    with Session(engine) as s:
        s.add(AuditEntry(ts=now(), actor=actor, action=action, target=target,
                         before=json.dumps(before) if before is not None else None,
                         after=json.dumps(after) if after is not None else None))
        s.commit()


def metrics(site=None):
    def scoped(query):
        return query.where(Run.site == site) if site else query

    def count(*conditions):
        with Session(engine) as s:
            return s.exec(scoped(select(func.count()).select_from(Run).where(*conditions))).one()

    day_ago = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(timespec="seconds")
    total = count()
    done = count(Run.status.in_(FINISHED))
    ok = count(Run.status == "success")
    with Session(engine) as s:
        avg = s.exec(scoped(select(func.avg(Run.duration_ms)).where(Run.status == "success"))).one()
    return {
        "runs_total": total,
        "running_now": count(Run.status == "running"),
        "failed_24h": count(Run.status.in_(BAD), Run.started_at > day_ago),
        "failed_7d": count(Run.status.in_(BAD), Run.started_at > week_ago),
        "success_rate": round(ok / done * 100) if done else None,
        "avg_duration_ms": round(avg or 0),
    }


def heatmap(days=7, site=None):
    """One cell per job per day: worst outcome that day wins."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    day = func.date(Run.started_at)
    query = (
        select(
            Run.job_id,
            day.label("day"),
            func.sum(case((Run.status == "success", 1), else_=0)).label("ok"),
            func.sum(case((Run.status.in_(BAD), 1), else_=0)).label("bad"),
        )
        .where(Run.started_at > since)
        .group_by(Run.job_id, text("day"))
        .order_by(text("day"))
    )
    if site:
        query = query.where(Run.site == site)
    with Session(engine) as s:
        return [dict(r._mapping) for r in s.exec(query)]


init()
