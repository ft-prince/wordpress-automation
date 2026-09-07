from ninja import Router, Schema
from ninja.errors import HttpError

from core import auth as dash_auth
from core import store

router = Router()


class Credentials(Schema):
    username: str = ""
    password: str


@router.get("/auth/status", auth=None)
def auth_status(request):
    return {"needs_setup": dash_auth.needs_setup()}


@router.post("/setup", auth=None)
def setup_account(request, body: Credentials):
    token = dash_auth.create_account(body.username, body.password)
    store.add_audit("dashboard", "account-created", body.username)
    return {"token": token}


@router.post("/login", auth=None)
def login(request, body: Credentials):
    user = dash_auth.verify(body.username, body.password)
    if not user:
        raise HttpError(401, "wrong username or password")
    return {"token": dash_auth.issue(user)}


@router.post("/logout", auth=None)
def logout(request):
    dash_auth.logout(request.headers.get("X-Auth-Token", ""))
    return {"ok": True}
