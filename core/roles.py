"""Four roles on Django groups. Superusers are admins. Reads are open to every
logged-in user; the gate is on approve / publish / delete / rollback / settings."""
from django.contrib.auth.models import Group, User
from ninja.errors import HttpError

ROLES = ("admin", "seo", "content", "viewer")
PERMS = {
    "approve": {"admin", "seo"},       # apply changes, approve briefs, on-page fixes
    "publish": {"admin", "seo"},
    "delete": {"admin"},
    "rollback": {"admin", "seo"},
    "settings": {"admin"},             # secrets, sites, users, Google
}


def role_of(user):
    if user.is_superuser:
        return "admin"
    names = set(user.groups.values_list("name", flat=True))
    return next((r for r in ROLES if r in names), "viewer")


def require(request, perm):
    role = role_of(request.auth)
    if role not in PERMS[perm]:
        raise HttpError(403, f"your role ({role}) cannot {perm}; ask an admin")
    return role


def set_role(user, role):
    if role not in ROLES:
        raise ValueError(f"role must be one of {', '.join(ROLES)}")
    user.groups.clear()
    user.groups.add(Group.objects.get_or_create(name=role)[0])
    user.is_superuser = user.is_staff = role == "admin"
    user.save()
    return role


def listing():
    return [{"id": u.pk, "username": u.username, "role": role_of(u), "last_login": u.last_login.isoformat(timespec="seconds") if u.last_login else None}
            for u in User.objects.order_by("id")]


def create(username, password, role):
    if not username.strip() or len(password) < 8:
        raise ValueError("username required; password must be 8+ characters")
    if User.objects.filter(username=username.strip()).exists():
        raise ValueError("username taken")
    user = User.objects.create_user(username.strip(), password=password)
    set_role(user, role)
    return {"id": user.pk, "username": user.username, "role": role}
