"""Dashboard login on Django's User model + a persistent token table.
The pre-Django account lived as a PBKDF2 hash in .env; the first successful login
against that hash upgrades it into a real User and the .env keys stop mattering."""
import hashlib
import hmac
import secrets as pysecrets
from datetime import timedelta

from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.utils import timezone
from ninja.security import APIKeyHeader

from core.models import ApiToken
from core.secrets import _parse

SESSION_DAYS = 7


def _legacy_hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000).hex()


def _legacy_ok(username, password):
    env = _parse()
    user, salt, digest = env.get("DASH_USER", ""), env.get("DASH_SALT", ""), env.get("DASH_PASS_HASH", "")
    if not (user and salt and digest):
        return False
    return (hmac.compare_digest(username.strip(), user)
            and hmac.compare_digest(_legacy_hash(password, salt), digest))


def needs_setup():
    if User.objects.exists():
        return False
    env = _parse()
    return not (env.get("DASH_USER") and env.get("DASH_PASS_HASH"))


def create_account(username, password):
    if not needs_setup():
        raise ValueError("account already exists - log in instead")
    if not username.strip() or len(password) < 8:
        raise ValueError("username required; password must be 8+ characters")
    user = User.objects.create_superuser(username.strip(), password=password)
    return issue(user)


def verify(username, password):
    """Returns the User on success, None otherwise."""
    user = authenticate(username=username.strip(), password=password)
    if user:
        return user
    if _legacy_ok(username, password) and not User.objects.filter(username=username.strip()).exists():
        return User.objects.create_superuser(username.strip(), password=password)
    return None


def issue(user):
    token = pysecrets.token_urlsafe(32)
    ApiToken.objects.create(key=token, user=user,
                            expires_at=timezone.now() + timedelta(days=SESSION_DAYS))
    return token


def check(token):
    if not token:
        return None
    row = ApiToken.objects.select_related("user").filter(key=token).first()
    if not row:
        return None
    if row.expires_at < timezone.now():
        row.delete()
        return None
    return row.user


def logout(token):
    ApiToken.objects.filter(key=token or "").delete()


class TokenAuth(APIKeyHeader):
    param_name = "X-Auth-Token"

    def authenticate(self, request, key):
        return check(key)
