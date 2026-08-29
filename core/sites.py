"""Multi-site registry: every WordPress site the dashboard manages.
sites.json (gitignored) holds credentials; the first site migrates from .env."""
import json
import os
import re
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITES_PATH = os.path.join(ROOT, "sites.json")
SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
_lock = threading.Lock()


def _read():
    if not os.path.exists(SITES_PATH):
        return _migrate_from_env()
    with open(SITES_PATH) as fh:
        return json.load(fh).get("sites", [])


def _write(sites):
    with open(SITES_PATH, "w") as fh:
        json.dump({"sites": sites}, fh, indent=2)
    os.chmod(SITES_PATH, 0o600)


def _migrate_from_env():
    """First run: lift the original site out of .env so nothing breaks."""
    from core.secrets import _parse

    env = _parse()
    if not env.get("WEBSITE_LINK"):
        return []
    url = env["WEBSITE_LINK"].rstrip("/")
    site = {
        "id": re.sub(r"[^a-z0-9-]", "-", url.split("//")[-1].split(".")[0].lower()) or "primary",
        "name": url.split("//")[-1],
        "url": url,
        "user": env.get("WP_USER", ""),
        "password": env.get("APPLICATION_PASSWORD", ""),
    }
    with _lock:
        _write([site])
    return [site]


def all_sites():
    """Public listing — passwords never leave the server."""
    return [{"id": s["id"], "name": s["name"], "url": s["url"], "user": s["user"]}
            for s in _read()]


def default_id():
    sites = _read()
    return sites[0]["id"] if sites else None


def env_for(site_id=None):
    """Credentials dict shaped exactly like .env, so wp.call(env=...) just works."""
    sites = _read()
    if not sites:
        raise ValueError("no sites configured")
    site = next((s for s in sites if s["id"] == site_id), sites[0])
    return {
        "WEBSITE_LINK": site["url"],
        "WP_USER": site["user"],
        "APPLICATION_PASSWORD": site["password"],
        "_site_id": site["id"],
    }


def test(url, user, password):
    """One authenticated round-trip against a candidate site."""
    import base64
    import urllib.error
    import urllib.request

    url = url.rstrip("/")
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    request = urllib.request.Request(
        f"{url}/wp-json/wp/v2/users/me?context=edit",
        headers={"Authorization": f"Basic {token}", "User-Agent": "wp-automation/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as resp:
            me = json.loads(resp.read())
            return {"ok": True, "user": me.get("name") or me.get("slug"), "roles": me.get("roles", [])}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf8", "replace")[:200]
        return {"ok": False, "error": f"HTTP {exc.code}: {detail}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}


def add(site_id, name, url, user, password):
    if not SAFE_ID.match(site_id or ""):
        raise ValueError("id must be lowercase letters/digits/dashes")
    if not url.startswith(("http://", "https://")):
        raise ValueError("url must start with http(s)://")
    if not (name and user and password):
        raise ValueError("name, user and application password are all required")
    check = test(url, user, password)
    if not check["ok"]:
        raise ValueError(f"connection test failed: {check['error']}")
    with _lock:
        sites = _read()
        if any(s["id"] == site_id for s in sites):
            raise ValueError(f"site '{site_id}' already exists")
        sites.append({"id": site_id, "name": name, "url": url.rstrip("/"),
                      "user": user, "password": password})
        _write(sites)
    return {"id": site_id, "connected_as": check["user"]}


def remove(site_id):
    with _lock:
        sites = _read()
        if len(sites) <= 1:
            raise ValueError("cannot remove the last site")
        remaining = [s for s in sites if s["id"] != site_id]
        if len(remaining) == len(sites):
            raise ValueError(f"no such site: {site_id}")
        _write(remaining)
    return True
