"""Minimal WordPress publisher. stdlib only, no deps, no framework."""
import base64
import json
import os
import urllib.error
import urllib.request

_ENV = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


def load_env(path=_ENV):
    """Parse a KEY=VALUE .env file. Missing file is fatal — fail fast, not silently."""
    if not os.path.exists(path):
        raise SystemExit(f"missing {path}")
    env = {}
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip().strip("\"'")
    return env


def _config(env):
    missing = [k for k in ("WEBSITE_LINK", "WP_USER", "APPLICATION_PASSWORD") if not env.get(k)]
    if missing:
        raise SystemExit(f".env missing required keys: {', '.join(missing)}")
    base = env["WEBSITE_LINK"].rstrip("/") + "/wp-json/wp/v2"
    token = base64.b64encode(f"{env['WP_USER']}:{env['APPLICATION_PASSWORD']}".encode()).decode()
    return base, token


TIMEOUT_SECONDS = 30


def call(path, payload=None, method="GET", env=None):
    """One HTTP call to the WP REST API. Raises RuntimeError with the API's own message."""
    base, token = _config(env or load_env())
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        f"{base}{path}",
        data=body,
        method=method,
        headers={
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json",
            "User-Agent": "wp-automation/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.loads(response.read() or b"null")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf8", "replace")[:400]
        raise RuntimeError(f"WP {exc.code} on {method} {path}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"cannot reach WordPress: {exc.reason}") from exc


def upload_media(image_bytes, filename, content_type="image/jpeg", env=None):
    """Upload an image to the WP media library. Returns the media object."""
    base, token = _config(env or load_env())
    request = urllib.request.Request(
        f"{base}/media",
        data=image_bytes,
        method="POST",
        headers={
            "Authorization": f"Basic {token}",
            "Content-Type": content_type,
            "Content-Disposition": f'attachment; filename="{filename}"',
            "User-Agent": "wp-automation/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS * 2) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf8", "replace")[:300]
        raise RuntimeError(f"WP media upload {exc.code}: {detail}") from exc


def publish(title, content, status="draft", dry_run=False, env=None, **fields):
    """Create a post. Defaults to draft — publishing live must be explicit."""
    if not title or not title.strip():
        raise ValueError("title is required")
    if not content or not content.strip():
        raise ValueError("content is required")
    if status not in ("draft", "publish", "pending", "private"):
        raise ValueError(f"bad status: {status}")

    payload = {"title": title, "content": content, "status": status, **fields}
    if dry_run:
        return {"dry_run": True, "payload": payload}
    return call("/posts", payload, method="POST", env=env)


def whoami():
    return call("/users/me?context=edit")


if __name__ == "__main__":
    user = whoami()
    print(f"connected as {user['slug']} ({', '.join(user['roles'])})")

    # this self-check IS the test suite. One real round-trip, cleaned up after.
    post = publish(
        "Automation smoke test",
        "<p>Created by wp.py to verify the REST connection. Safe to delete.</p>",
    )
    assert post["status"] == "draft", post["status"]
    assert post["id"] > 0
    print(f"draft #{post['id']} created -> {post['link']}")

    call(f"/posts/{post['id']}?force=true", method="DELETE")
    print(f"draft #{post['id']} deleted. round-trip OK")
