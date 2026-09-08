from ninja import Router, Schema
from ninja.errors import HttpError

import threading
import time

from core import auth as dash_auth
from core import store

router = Router()

# ponytail: in-memory per-IP throttle; enough for one process behind a tunnel.
LOGIN_ATTEMPTS, LOGIN_WINDOW = 8, 300
_attempts = {}
_lock = threading.Lock()


def _client_ip(request):
    fwd = request.META.get("HTTP_CF_CONNECTING_IP") or request.META.get("HTTP_X_FORWARDED_FOR", "")
    return (fwd.split(",")[0].strip() or request.META.get("REMOTE_ADDR", "?"))


def _throttle(request):
    ip, now = _client_ip(request), time.time()
    with _lock:
        recent = [t for t in _attempts.get(ip, []) if now - t < LOGIN_WINDOW]
        if len(recent) >= LOGIN_ATTEMPTS:
            raise HttpError(429, f"too many login attempts; wait {LOGIN_WINDOW // 60} minutes")
        _attempts[ip] = recent + [now]


class Credentials(Schema):
    username: str = ""
    password: str


@router.get("/auth/status", auth=None)
def auth_status(request):
    return {"needs_setup": dash_auth.needs_setup()}


@router.post("/setup", auth=None)
def setup_account(request, body: Credentials):
    _throttle(request)
    token = dash_auth.create_account(body.username, body.password)
    store.add_audit("dashboard", "account-created", body.username)
    return {"token": token}


@router.post("/login", auth=None)
def login(request, body: Credentials):
    _throttle(request)
    user = dash_auth.verify(body.username, body.password)
    if not user:
        store.add_audit(_client_ip(request), "login-failed", body.username[:64])
        raise HttpError(401, "wrong username or password")
    return {"token": dash_auth.issue(user)}


@router.post("/logout", auth=None)
def logout(request):
    dash_auth.logout(request.headers.get("X-Auth-Token", ""))
    return {"ok": True}
