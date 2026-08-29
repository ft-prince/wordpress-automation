"""Dashboard login: one account, salted-hash credentials in .env, in-memory sessions.
sessions die on restart — you log in again. No session table needed."""
import hashlib
import hmac
import secrets as pysecrets
import time

from core.secrets import _parse, set_value

SESSION_HOURS = 24 * 7
_sessions = {}  # token -> expiry epoch


def _hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000).hex()


def needs_setup():
    env = _parse()
    return not (env.get("DASH_USER") and env.get("DASH_PASS_HASH"))


def create_account(username, password):
    if not needs_setup():
        raise ValueError("account already exists — log in instead")
    if not username.strip() or len(password) < 8:
        raise ValueError("username required; password must be 8+ characters")
    salt = pysecrets.token_hex(16)
    set_value("DASH_USER", username.strip())
    set_value("DASH_SALT", salt)
    set_value("DASH_PASS_HASH", _hash(password, salt))
    return issue()


def verify(username, password):
    env = _parse()
    expected_user = env.get("DASH_USER", "")
    salt = env.get("DASH_SALT", "")
    expected_hash = env.get("DASH_PASS_HASH", "")
    if not (expected_user and salt and expected_hash):
        return False
    user_ok = hmac.compare_digest(username.strip(), expected_user)
    pass_ok = hmac.compare_digest(_hash(password, salt), expected_hash)
    return user_ok and pass_ok


def issue():
    token = pysecrets.token_urlsafe(32)
    _sessions[token] = time.time() + SESSION_HOURS * 3600
    return token


def check(token):
    expiry = _sessions.get(token or "")
    if not expiry:
        return False
    if time.time() > expiry:
        _sessions.pop(token, None)
        return False
    return True


def logout(token):
    _sessions.pop(token or "", None)
