"""PressPilot Django settings. Single operator, single SQLite file, no cloud."""
import secrets as pysecrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DIST_DIR = BASE_DIR / "dashboard" / "dist"
ENV_PATH = BASE_DIR / ".env"


def _read_env():
    """Tiny KEY=VALUE parser. core.secrets has the full one, but importing `core`
    here would boot the app while settings are still loading."""
    if not ENV_PATH.exists():
        return {}
    out = {}
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            out[key.strip()] = value.strip().strip("\"'")
    return out


_env = _read_env()

SECRET_KEY = _env.get("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    SECRET_KEY = pysecrets.token_urlsafe(48)
    with open(ENV_PATH, "a") as fh:
        fh.write(f"\nDJANGO_SECRET_KEY={SECRET_KEY}\n")

DEBUG = _env.get("DJANGO_DEBUG", "0") == "1"
ALLOWED_HOSTS = [h for h in _env.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "presspilot.urls"
WSGI_APPLICATION = "presspilot.wsgi.application"
ASGI_APPLICATION = "presspilot.asgi.application"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
        "django.template.context_processors.request",
    ]},
}]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "automation.db",
        "OPTIONS": {"timeout": 10, "init_command": "PRAGMA journal_mode=WAL;"},
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 8}},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
