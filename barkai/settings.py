"""
Django settings for the barkAI project.

Configuration philosophy
------------------------
* Environment-driven settings: values are read straight from the process
  environment via os.getenv() - python-dotenv is intentionally NOT used.
  Export variables before running Django, e.g.:
      set -a; source .env; set +a
* DEBUG defaults to True so a fresh clone runs out of the box for local
  development; production MUST export DEBUG=False explicitly.
* Static assets live in a project-wide "static/" folder so Barkley's reaction
  MP4s under static/mascot/ are served by runserver while DEBUG is enabled.
* The database comes from a single connection string, DATABASE_URL. While DEBUG
  is on, a missing URL means zero-config SQLite (enough for a quick look and for
  the test suite); with DEBUG off the app refuses to boot instead of connecting
  with guessed credentials.
"""

import os
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlparse

from django.core.exceptions import ImproperlyConfigured
from django.utils.translation import gettext_lazy as _

# Build paths inside the project like this: BASE_DIR / "subdir".
BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: str = "False") -> bool:
    """Parse an environment variable as a boolean, tolerating sloppy values."""
    return os.getenv(name, default).strip().lower() in ("1", "true", "t", "yes")


def env_csv(name: str, default: str = "") -> list[str]:
    """Split a comma-separated environment variable into a cleaned list."""
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


def env_str(name: str, default: str = "") -> str:
    """Read an environment variable, treating a blank value as unset.

    A key that is present but empty (e.g. ``GROQ_MODEL=`` in .env) must not
    override the default, otherwise the app would run with an empty model id.
    """
    return os.getenv(name, "").strip() or default


def env_int(name: str, default: int) -> int:
    """Read an integer environment variable, falling back on blank/invalid."""
    try:
        return int(env_str(name, str(default)))
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    """Read a float environment variable, falling back on blank/invalid."""
    try:
        return float(env_str(name, str(default)))
    except ValueError:
        return default


# --- Core Django ----------------------------------------------------------
# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv("SECRET_KEY", "django-insecure-dev-only-key-change-me")

# SECURITY WARNING: never run with debug enabled in production.
# Defaults to True when unset for a frictionless local development experience.
DEBUG = env_bool("DEBUG", default="True")

# testserver is included so the Django test client works out of the box.
ALLOWED_HOSTS = env_csv("ALLOWED_HOSTS", default="localhost,127.0.0.1,[::1],0.0.0.0,testserver")

# Application definition
INSTALLED_APPS = [
    # Django core
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party apps
    "corsheaders",  # Cross-origin headers for the REST API
    # Local apps - each app owns its models/views/urls/templates.
    "chat",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # WhiteNoise serves the collected static files from the app process itself,
    # so one Cloud Run service is enough (no bucket/CDN required). It must sit
    # directly after SecurityMiddleware to short-circuit static requests early.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    # LocaleMiddleware must sit after SessionMiddleware (it reads the session
    # language) and before CommonMiddleware (it rewrites the request path).
    "django.middleware.locale.LocaleMiddleware",
    # CORS middleware must sit above CommonMiddleware so headers are added early.
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "barkai.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # Project-wide templates (base.html, includes/, error pages) live in the
        # root templates/ folder; each app keeps its own page templates too.
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                # Exposes LANGUAGE_CODE / LANGUAGES to templates (html lang, toggle).
                "django.template.context_processors.i18n",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                # Exposes ASSET_VERSION: every static <link>/<script> appends it
                # as `?v=` so a deployed asset change is not hidden by WhiteNoise's
                # one-year cache (see the Static files section).
                "barkai.context_processors.asset_version",
            ],
        },
    },
]

WSGI_APPLICATION = "barkai.wsgi.application"

# --- Database -------------------------------------------------------------
# A single supported way to configure the database: DATABASE_URL (PostgreSQL +
# pgvector, e.g. Neon/Supabase). No URL while DEBUG is on falls back to a
# zero-config SQLite file — handy for a quick look and for the test suite, but
# it has no pgvector, so retrieval uses the Python cosine fallback. With DEBUG
# off there is deliberately no fallback (see below): refusing to boot beats
# silently connecting with guessed credentials.
def database_from_url(url: str) -> dict:
    """Turn a ``postgres://`` connection string into a Django DATABASES entry."""
    parsed = urlparse(url)
    if parsed.scheme not in ("postgres", "postgresql", "postgresql+psycopg"):
        raise ValueError(f"Unsupported DATABASE_URL scheme: {parsed.scheme!r}")
    options = dict(parse_qsl(parsed.query))
    config = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": parsed.path.lstrip("/") or "postgres",
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname or "",
        "PORT": str(parsed.port or ""),
    }
    if options:
        config["OPTIONS"] = options
    return config


DATABASE_URL = env_str("DATABASE_URL", "")

if DATABASE_URL:
    DATABASES = {"default": database_from_url(DATABASE_URL)}
elif DEBUG:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    raise ImproperlyConfigured(
        "No database configured: export DATABASE_URL (PostgreSQL + pgvector) "
        "before running with DEBUG=False. There is no implicit production "
        "fallback."
    )

# --- Password validation --------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- Internationalization -------------------------------------------------
# English is the source language; Danish is the primary target audience.
# LocaleMiddleware negotiates the active language from the browser's
# Accept-Language header and the visitor can override it with the navbar toggle.
LANGUAGE_CODE = "en"
LANGUAGES = [
    ("en", _("English")),
    ("da", _("Danish")),
]
# Where `makemessages` writes and `compilemessages` reads the .po/.mo catalogs.
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# --- Static files ---------------------------------------------------------
STATIC_URL = "static/"

# Project-wide static assets. Barkley's mascot MP4s live in static/mascot/ and
# are served at /static/mascot/<state>.mp4 by runserver while DEBUG is enabled.
STATICFILES_DIRS = [BASE_DIR / "static"]

# Target directory for `python manage.py collectstatic` in production.
STATIC_ROOT = BASE_DIR / "staticfiles"

# Static file storage. The *Compressed* (not Manifest) WhiteNoise backend is used
# on purpose: without a manifest, `{% static %}` keeps resolving even before
# `collectstatic` has run, which keeps local development and the test suite happy.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
# Immutable assets are served with a one-year cache header.
WHITENOISE_MAX_AGE = env_int("WHITENOISE_MAX_AGE", 31536000)

# Cache-buster for the static assets. Every static URL in the templates carries
# `?v={{ ASSET_VERSION }}` (exposed by barkai.context_processors.asset_version):
# the storage backend is deliberately the non-Manifest one, so an asset URL never
# changes when its content does, and with a one-year `max-age` the browser would
# not even revalidate it. Without the query string a deployed frontend fix (CSS,
# JS, mascot clips) stays invisible to anyone who already visited the site.
def _asset_version_default() -> str:
    """Derive the cache-busting token from the newest static asset.

    Used when ASSET_VERSION is not set in the environment. It reads the mtime of
    the files that are actually served — STATIC_ROOT once `collectstatic` has run,
    the source folders otherwise — which moves exactly when the assets move: on a
    deploy that rebuilds them, or when a clip is replaced in place. A deploy that
    changes nothing keeps the same token, so the cached copy stays cached, and
    nothing has to be remembered by hand (a missed manual bump would silently
    serve the previous CSS for a year). It is read once, at import time: a process
    restart is what picks up files that changed under a running server.
    """
    newest = 0.0
    for root in (STATIC_ROOT, *STATICFILES_DIRS):
        for pattern in ("css/*.css", "js/*.js", "mascot/*.mp4"):
            for path in root.glob(pattern):
                try:
                    newest = max(newest, path.stat().st_mtime)
                except OSError:  # pragma: no cover - unreadable file, skipped
                    continue
    return str(int(newest)) if newest else "dev"


# Pin it only to override the derived token (e.g. to the commit SHA on an
# environment where the files' timestamps are not a reliable signal).
ASSET_VERSION = env_str("ASSET_VERSION", _asset_version_default())

# --- CORS (django-cors-headers) -------------------------------------------
CORS_ALLOWED_ORIGINS = env_csv("CORS_ALLOWED_ORIGINS")

# Local development trusts all origins (the Tailwind UI is same-origin anyway);
# production should pin CORS_ALLOWED_ORIGINS to the real frontend origin(s).
CORS_ALLOW_ALL_ORIGINS = DEBUG and not CORS_ALLOWED_ORIGINS

# Default primary key field type
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- barkAI application settings ------------------------------------------
# LLM agent (Groq). An empty GROQ_API_KEY keeps the offline mock in
# chat/services.py, so local dev and the test suite need no network or secret.
GROQ_API_KEY = env_str("GROQ_API_KEY", "")
GROQ_MODEL = env_str("GROQ_MODEL", "qwen/qwen3.8-27b")
GROQ_TIMEOUT_SECONDS = env_float("GROQ_TIMEOUT_SECONDS", 20.0)
GROQ_MAX_TOKENS = env_int("GROQ_MAX_TOKENS", 512)
GROQ_TEMPERATURE = env_float("GROQ_TEMPERATURE", 0.5)
# How many previous turns are handed to the model as conversation context.
AGENT_HISTORY_LIMIT = env_int("AGENT_HISTORY_LIMIT", 20)
# How much knowledge-base text is injected into the system prompt.
AGENT_KNOWLEDGE_MAX_CHARS = env_int("AGENT_KNOWLEDGE_MAX_CHARS", 12000)

# --- RAG / embeddings -----------------------------------------------------
# Pluggable embedding provider for the retrieval layer:
#   "cloudflare" -> Cloudflare Workers AI (multilingual, 1024 dims)
#   "none"       -> retrieval disabled (context stuffing only)
EMBEDDING_PROVIDER = env_str("EMBEDDING_PROVIDER", "none")
EMBEDDING_MODEL = env_str("EMBEDDING_MODEL", "@cf/baai/bge-m3")
EMBEDDING_DIMENSIONS = env_int("EMBEDDING_DIMENSIONS", 1024)
EMBEDDING_TIMEOUT_SECONDS = env_float("EMBEDDING_TIMEOUT_SECONDS", 30.0)
EMBEDDING_BATCH_SIZE = env_int("EMBEDDING_BATCH_SIZE", 32)
CLOUDFLARE_ACCOUNT_ID = env_str("CLOUDFLARE_ACCOUNT_ID", "")
CLOUDFLARE_API_TOKEN = env_str("CLOUDFLARE_API_TOKEN", "")
# Retrieval knobs.
RAG_ENABLED = env_bool("RAG_ENABLED", default="False")
RAG_TOP_K = env_int("RAG_TOP_K", 5)
# Max chunks a single document may contribute to one prompt. Without it a long,
# generic README (this project's own, say) can fill every slot.
RAG_MAX_PER_SOURCE = env_int("RAG_MAX_PER_SOURCE", 2)
# Minimum cosine similarity for a chunk to reach the prompt. Tuned for
# @cf/baai/bge-m3: below ~0.35 generic matches start leaking in.
RAG_MIN_SCORE = env_float("RAG_MIN_SCORE", 0.35)
# Chunks longer than this many characters are split during indexing.
RAG_CHUNK_MAX_CHARS = env_int("RAG_CHUNK_MAX_CHARS", 1200)

# --- Email & interview notifications --------------------------------------
# BarklAI emails Andrea when a recruiter asks for an interview. The console
# backend is the default, so local runs and the test suite need no SMTP server;
# production exports the SMTP settings (Gmail example in the README):
#   EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
#   EMAIL_HOST=smtp.gmail.com  EMAIL_PORT=587  EMAIL_USE_TLS=True
#   EMAIL_HOST_USER=<gmail address>  EMAIL_HOST_PASSWORD=<app password>
EMAIL_BACKEND = env_str("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = env_str("EMAIL_HOST", "")
EMAIL_PORT = env_int("EMAIL_PORT", 587)
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", default="True")
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", default="False")
EMAIL_HOST_USER = env_str("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env_str("EMAIL_HOST_PASSWORD", "")
# Hard cap so an unreachable SMTP server can never hang the recruiter's chat.
EMAIL_TIMEOUT = env_int("EMAIL_TIMEOUT", 10)
DEFAULT_FROM_EMAIL = env_str("DEFAULT_FROM_EMAIL", "BarkAI <noreply@localhost>")
# Where interview requests are reported. Blank disables the notification (the
# request is still stored and visible in the admin).
INTERVIEW_NOTIFY_EMAIL = env_str("INTERVIEW_NOTIFY_EMAIL", "")
# Public base URL, used to build the admin deep link inside the notification.
SITE_BASE_URL = env_str("SITE_BASE_URL", "")

# --- Chat abuse protection ------------------------------------------------
# The chat endpoint is public and costs an LLM call per message, so both the
# session and the client IP get a fixed-window cap (see chat/throttle.py).
CHAT_RATE_LIMIT_PER_SESSION = env_int("CHAT_RATE_LIMIT_PER_SESSION", 20)
CHAT_RATE_LIMIT_PER_IP = env_int("CHAT_RATE_LIMIT_PER_IP", 60)
CHAT_RATE_LIMIT_WINDOW_SECONDS = env_int("CHAT_RATE_LIMIT_WINDOW_SECONDS", 300)

# --- Agent guardrails -----------------------------------------------------
# Retry once when the model answers in a different language from the question
# (the "Danish question, English answer" regression — see chat/services.py).
AGENT_LANGUAGE_GUARD = env_bool("AGENT_LANGUAGE_GUARD", default="True")
# Model used when the primary one fails (decommissioned preview model, 400/404):
# a *production* Groq model, so a deprecation cannot take the whole chat down.
GROQ_MODEL_FALLBACK = env_str("GROQ_MODEL_FALLBACK", "llama-3.3-70b-versatile")

# --- Production security --------------------------------------------------
# Every flag is env-driven and defaults to "safe once DEBUG is off", so a
# production deployment gets HTTPS enforcement for free while local development
# stays plain HTTP on localhost. `python manage.py check --deploy` is the
# sanity check: it should report no warnings with DEBUG=False and these set.
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", default=str(not DEBUG))
SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", default=str(not DEBUG))
CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", default=str(not DEBUG))
# HSTS: a year, and only meaningful once HTTPS is guaranteed end to end.
SECURE_HSTS_SECONDS = env_int("SECURE_HSTS_SECONDS", 0 if DEBUG else 31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool(
    "SECURE_HSTS_INCLUDE_SUBDOMAINS", default=str(not DEBUG)
)
# Preload adds the directive to the HSTS header; the domain is only actually
# preloaded if it is submitted at hstspreload.org, so enabling it with DEBUG off
# is harmless and makes `check --deploy` clean. Set it to False if you never
# intend to submit.
SECURE_HSTS_PRELOAD = env_bool("SECURE_HSTS_PRELOAD", default=str(not DEBUG))
SECURE_REFERRER_POLICY = env_str("SECURE_REFERRER_POLICY", "same-origin")
# Managed platforms (Cloud Run, Heroku, Fly) terminate TLS and forward the
# scheme, so Django has to be told to trust that header.
if env_bool("TRUST_PROXY_SSL_HEADER", default="False"):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# Origins allowed to send POSTs (comma-separated), e.g. the custom domain.
CSRF_TRUSTED_ORIGINS = env_csv("CSRF_TRUSTED_ORIGINS")

# --- Privacy / GDPR -------------------------------------------------------
# Conversations older than this many days are purged by
# `python manage.py purge_old_sessions` (data minimisation, art. 5 GDPR).
SESSION_RETENTION_DAYS = env_int("SESSION_RETENTION_DAYS", 90)
# Address shown in the privacy notice for data-subject requests.
PRIVACY_CONTACT_EMAIL = env_str("PRIVACY_CONTACT_EMAIL", "latorre.andrea.93@gmail.com")

# Knowledge ingestion from GitHub (see `python manage.py sync_knowledge`).
# How old a knowledge document may be before `knowledge_status --fail-on-stale`
# (and the scheduled job that runs it) starts complaining.
KNOWLEDGE_STALE_DAYS = env_int("KNOWLEDGE_STALE_DAYS", 30)

# Knowledge ingestion from GitHub (see `python manage.py sync_knowledge`).
GITHUB_USERNAME = env_str("GITHUB_USERNAME", "")
GITHUB_EXTRA_REPOS = env_csv("GITHUB_EXTRA_REPOS")
# Repositories to keep OUT of the knowledge base (template/boilerplate READMEs,
# abandoned projects…). Accepts `owner/repo`, a full GitHub URL, or just the bare
# repository name (matched case-insensitively).
GITHUB_EXCLUDE_REPOS = env_csv("GITHUB_EXCLUDE_REPOS")
GITHUB_TOKEN = env_str("GITHUB_TOKEN", "")
GITHUB_INCLUDE_FORKS = env_bool("GITHUB_INCLUDE_FORKS", default="False")
GITHUB_API_TIMEOUT_SECONDS = env_float("GITHUB_API_TIMEOUT_SECONDS", 15.0)
GITHUB_README_MAX_CHARS = env_int("GITHUB_README_MAX_CHARS", 14000)

# Public URL of the curated career profile (``chat/knowledge/andrea_profile.md``),
# e.g. its GitHub blob URL. Optional: when set, a citation that points at the
# profile is clickable too; the README citations use the GitHub URL the sync
# already stores, which always points at the file on the default branch.
PROFILE_URL = env_str("PROFILE_URL", "")
