from django.contrib.auth.models import User
from ninja import Router, Schema
from ninja.errors import HttpError

from core import roles, store

router = Router()


class UserCreate(Schema):
    username: str
    password: str
    role: str = "viewer"


class UserPatch(Schema):
    role: str | None = None
    password: str | None = None


@router.get("/me")
def me(request):
    return {"username": request.auth.username, "role": roles.role_of(request.auth), "perms": sorted(p for p, r in roles.PERMS.items() if roles.role_of(request.auth) in r)}


@router.get("/users")
def list_users(request):
    roles.require(request, "settings")
    return roles.listing()


@router.post("/users")
def create_user(request, body: UserCreate):
    roles.require(request, "settings")
    result = roles.create(body.username, body.password, body.role)
    store.add_audit(request.auth.username, "user-created", body.username, None, {"role": body.role})
    return result


@router.patch("/users/{user_id}")
def patch_user(request, user_id: int, body: UserPatch):
    roles.require(request, "settings")
    user = User.objects.filter(pk=user_id).first()
    if not user:
        raise HttpError(404, "no such user")
    if body.role:
        if user.pk == request.auth.pk and body.role != "admin":
            raise HttpError(400, "you cannot demote yourself")
        roles.set_role(user, body.role)
    if body.password:
        if len(body.password) < 8:
            raise HttpError(400, "password must be 8+ characters")
        user.set_password(body.password)
        user.save()
    store.add_audit(request.auth.username, "user-updated", user.username, None, {"role": body.role, "password": bool(body.password)})
    return {"id": user.pk, "username": user.username, "role": roles.role_of(user)}


@router.delete("/users/{user_id}")
def delete_user(request, user_id: int):
    roles.require(request, "settings")
    if user_id == request.auth.pk:
        raise HttpError(400, "you cannot delete yourself")
    User.objects.filter(pk=user_id).delete()
    return {"deleted": True}
