"""Topic engine: discovery, approval queue, and what-to-write-next.
Replaces topics.txt — SQLite is the source of truth, the old file migrates in."""
import json
import os
import re
import threading

from core import sites, store, wp_api

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEGACY_TOPICS = os.path.join(ROOT, "topics.txt")
LEGACY_DONE = os.path.join(ROOT, "posted.txt")

STATUSES = ("suggested", "approved", "rejected", "written")
SOURCES = ("site-gap", "serp", "trending", "cluster", "manual")
LOW_QUEUE_THRESHOLD = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS topics (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  title      TEXT NOT NULL,
  source     TEXT NOT NULL DEFAULT 'manual',
  category   TEXT DEFAULT '',
  relevance  INTEGER DEFAULT 50,
  why        TEXT DEFAULT '',
  site       TEXT DEFAULT '',
  status     TEXT NOT NULL DEFAULT 'suggested',
  position   INTEGER DEFAULT 0,
  created_at TEXT NOT NULL,
  post_id    INTEGER
);
"""
_migrated = threading.Event()


def _conn():
    conn = store.connect()
    conn.executescript(SCHEMA)
    if not _migrated.is_set():
        _migrate(conn)
        _migrated.set()
    return conn


def _migrate(conn):
    """One-time lift of topics.txt/posted.txt into the table."""
    if conn.execute("SELECT COUNT(*) FROM topics").fetchone()[0]:
        return
    done = set()
    if os.path.exists(LEGACY_DONE):
        done = {l.strip() for l in open(LEGACY_DONE) if l.strip()}
    if os.path.exists(LEGACY_TOPICS):
        for line in open(LEGACY_TOPICS):
            line = line.strip()
            if line and not line.startswith("#"):
                conn.execute(
                    "INSERT INTO topics (title,source,status,why,created_at) VALUES (?,?,?,?,?)",
                    (line, "manual", "written" if line in done else "approved",
                     "added earlier", store.now()),
                )


def _rows(sql, params=()):
    with _conn() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def listing(status=None, site=None):
    where, params = [], []
    if status:
        where.append("status=?")
        params.append(status)
    if site:
        where.append("(site=? OR site='')")
        params.append(site)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    order = "position, id" if status == "approved" else "relevance DESC, id DESC"
    return _rows(f"SELECT * FROM topics {clause} ORDER BY {order} LIMIT 200", params)


def add(title, source="manual", category="", relevance=50, why="", site="", status="suggested"):
    title = (title or "").strip()
    if not title:
        raise ValueError("title is required")
    if status not in STATUSES:
        raise ValueError(f"bad status: {status}")
    # Never re-suggest something already known under any status.
    existing = _rows("SELECT id FROM topics WHERE lower(title)=?", (title.lower(),))
    if existing:
        return None
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO topics (title,source,category,relevance,why,site,status,position,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (title, source, category, int(relevance), why, site, status,
             _next_position(conn) if status == "approved" else 0, store.now()),
        )
        return cur.lastrowid


def _next_position(conn):
    row = conn.execute("SELECT MAX(position) FROM topics WHERE status='approved'").fetchone()
    return (row[0] or 0) + 1


def update(topic_id, **fields):
    allowed = {"title", "category", "site", "status", "relevance", "why"}
    changes = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not changes:
        raise ValueError("nothing to change")
    if changes.get("status") not in (None, *STATUSES):
        raise ValueError(f"bad status: {changes['status']}")
    with _conn() as conn:
        if changes.get("status") == "approved":
            changes["position"] = _next_position(conn)
        sets = ", ".join(f"{k}=?" for k in changes)
        conn.execute(f"UPDATE topics SET {sets} WHERE id=?", (*changes.values(), topic_id))
    rows = _rows("SELECT * FROM topics WHERE id=?", (topic_id,))
    if not rows:
        raise KeyError(topic_id)
    return rows[0]


def move(topic_id, direction):
    """Swap queue position with the neighbour above/below."""
    with _conn() as conn:
        queue = [dict(r) for r in conn.execute(
            "SELECT id, position FROM topics WHERE status='approved' ORDER BY position, id")]
        idx = next((i for i, t in enumerate(queue) if t["id"] == topic_id), None)
        if idx is None:
            raise KeyError(topic_id)
        swap = idx - 1 if direction == "up" else idx + 1
        if not 0 <= swap < len(queue):
            return False
        # Normalise positions then swap the two — keeps ordering stable forever.
        for i, t in enumerate(queue):
            conn.execute("UPDATE topics SET position=? WHERE id=?", (i + 1, t["id"]))
        conn.execute("UPDATE topics SET position=? WHERE id=?", (swap + 1, queue[idx]["id"]))
        conn.execute("UPDATE topics SET position=? WHERE id=?", (idx + 1, queue[swap]["id"]))
    return True


def delete(topic_id):
    with _conn() as conn:
        conn.execute("DELETE FROM topics WHERE id=?", (topic_id,))
    return True


def next_approved(site=None):
    """What blog.py writes next: first queued topic for this site (or unassigned)."""
    rows = listing(status="approved", site=site)
    return rows[0] if rows else None


def mark_written(topic_id, post_id=None):
    with _conn() as conn:
        conn.execute("UPDATE topics SET status='written', post_id=? WHERE id=?", (post_id, topic_id))


def queue_depth(site=None):
    return len(listing(status="approved", site=site))


# ── Discovery ──────────────────────────────────────────────────────────────

DISCOVER_PROMPTS = {
    "site-gap": """This company's website has these existing pages and blog posts:
{inventory}

Search the web for what companies in this exact niche publish about. Suggest {n} blog
topics this site has NOT covered yet that directly support its business. Favour topics
that connect to its product/solution pages.""",
    "serp": """Search the web for blog articles currently ranking well in this niche:
{inventory}

Suggest {n} topics where the searcher intent is clear and this company could
realistically compete. Prefer specific, long-tail angles over broad ones.""",
    "trending": """Search the web for recent news, releases and trends (last few months)
relevant to this company's field:
{inventory}

Suggest {n} timely blog topics a practitioner would genuinely want to read this month.""",
}

DISCOVER_FORMAT = """
For each topic reply with why it's worth writing and how relevant it is to THIS site.
Reply with ONLY this JSON array, nothing else:
[{{"title": "...", "category": "...", "relevance": 0-100, "why": "one concrete sentence"}}]"""


def _site_inventory(site=None):
    """Titles of everything published — the model's picture of what the site is."""
    env = sites.env_for(site)
    lines = [f"Site: {env['WEBSITE_LINK']}"]
    try:
        for p in wp_api.posts("publish", 30, site=site):
            lines.append(f"- blog post: {p['title']}")
    except RuntimeError:
        pass
    try:
        import wp

        for base in ("pages", "solution"):
            try:
                for item in wp.call(f"/{base}?per_page=30&_fields=title", env=env):
                    lines.append(f"- page: {item['title']['rendered']}")
            except RuntimeError:
                pass
    except Exception:
        pass
    return "\n".join(lines[:60])


def discover(site=None, per_source=4):
    """Run every discovery source, dedup, store as 'suggested'. Returns new topics."""
    import gen
    from concurrent.futures import ThreadPoolExecutor

    key = gen.api_key(gen.load_env())
    inventory = _site_inventory(site)

    def ask(source):
        prompt = DISCOVER_PROMPTS[source].format(inventory=inventory, n=per_source) + DISCOVER_FORMAT
        try:
            data = gen._post(
                "/chat/completions",
                {"model": gen.RESEARCH_MODEL,
                 "messages": [{"role": "user", "content": prompt}]},
                key,
            )
            text = data["choices"][0]["message"]["content"]
            match = re.search(r"\[.*\]", text, re.S)
            candidates = json.loads(match.group(0)) if match else []
        except (RuntimeError, json.JSONDecodeError):
            return []
        out = []
        for c in candidates[:per_source]:
            if not isinstance(c, dict) or not (c.get("title") or "").strip():
                continue
            out.append({
                "title": c["title"].strip()[:200],
                "source": source,
                "category": (c.get("category") or "").strip()[:60],
                "relevance": max(0, min(100, int(c.get("relevance") or 50))),
                "why": (c.get("why") or "").strip()[:300],
            })
        return out

    with ThreadPoolExecutor(max_workers=3) as pool:
        batches = list(pool.map(ask, DISCOVER_PROMPTS))

    created = []
    for batch in batches:
        for c in batch:
            new_id = add(site=site or "", status="suggested", **c)
            if new_id:
                created.append({**c, "id": new_id})
    store.add_audit("discovery", "topics-discovered", site or "default",
                    None, {"found": len(created)})
    return created
