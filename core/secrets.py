"""Secrets live in .env. Values are never returned to the UI — masked only."""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(ROOT, ".env")
SAFE_KEY = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
# Values for these keys are shown in full — they are configuration, not credentials.
PUBLIC_KEYS = {"WEBSITE_LINK", "WP_USER", "APPLICATION_NAME", "GROQ_MODEL", "LLM_BASE_URL", "LLM_MODEL", "PUBLIC_URL", "DJANGO_ALLOWED_HOSTS", "GOOGLE_CSE_ID"}


def mask(value):
    if not value:
        return ""
    if len(value) <= 8:
        return "…" * 4
    return f"{value[:4]}…{value[-4:]}"


def _parse():
    if not os.path.exists(ENV_PATH):
        return {}
    entries = {}
    with open(ENV_PATH) as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                entries[key.strip()] = value.strip().strip("\"'")
    return entries


def listing():
    return [
        {
            "key": key,
            "value": value if key in PUBLIC_KEYS else mask(value),
            "secret": key not in PUBLIC_KEYS,
            "used_by": used_by(key),
        }
        for key, value in sorted(_parse().items())
    ]


def used_by(key):
    from core import registry

    return [j["id"] for j in registry.all_jobs() if key in (j.get("env") or [])]


def remove(key):
    """Drop a key from .env entirely (used once the legacy dashboard login is upgraded)."""
    if not os.path.exists(ENV_PATH):
        return False
    with open(ENV_PATH) as fh:
        lines = fh.read().splitlines()
    kept = [l for l in lines if not l.strip().startswith(f"{key}=")]
    if len(kept) == len(lines):
        return False
    with open(ENV_PATH, "w") as fh:
        fh.write("\n".join(kept).rstrip("\n") + "\n")
    return True


def set_value(key, value):
    """Rewrite .env in place, preserving comments and order. Never echoes the value back."""
    if not SAFE_KEY.match(key or ""):
        raise ValueError(f"invalid key: {key!r}")
    if value is None or "\n" in value:
        raise ValueError("value must be a single line")

    lines = []
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH) as fh:
            lines = fh.read().splitlines()

    replaced = False
    out = []
    for line in lines:
        if line.strip().startswith(f"{key}=") and not line.strip().startswith("#"):
            out.append(f"{key}={value}")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(f"{key}={value}")

    with open(ENV_PATH, "w") as fh:
        fh.write("\n".join(out).rstrip("\n") + "\n")
    os.chmod(ENV_PATH, 0o600)
    return True
