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
"""

import os
from pathlib import Path

# Build paths inside the project like this: BASE_DIR / "subdir".
BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: str = "False") -> bool:
    """Parse an environment variable as a boolean, tolerating sloppy values."""
    return os.getenv(name, default).strip().lower() in ("1", "true", "t", "yes")


def env_csv(name: str, default: str = "") -> list[str]:
    """Split a comma-separated environment variable into a cleaned list."""
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


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
    "django.contrib.sessions.middleware.SessionMiddleware",
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
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "barkai.wsgi.application"

# --- Database -------------------------------------------------------------
# Local development (DEBUG=True) keeps the zero-config SQLite database, so a
# fresh clone runs without any external service. Production deployments
# (DEBUG=False) MUST read the database settings from the environment via
# os.getenv() instead of relying on anything hard-coded in this file.
if DEBUG:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": os.getenv("DB_ENGINE", "django.db.backends.postgresql"),
            "NAME": os.getenv("DB_NAME", "barkai"),
            "USER": os.getenv("DB_USER", "barkai"),
            "PASSWORD": os.getenv("DB_PASSWORD", ""),
            "HOST": os.getenv("DB_HOST", "127.0.0.1"),
            "PORT": os.getenv("DB_PORT", "5432"),
        }
    }

# --- Password validation --------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- Internationalization -------------------------------------------------
LANGUAGE_CODE = "en-us"
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

# --- CORS (django-cors-headers) -------------------------------------------
CORS_ALLOWED_ORIGINS = env_csv("CORS_ALLOWED_ORIGINS")

# Local development trusts all origins (the Tailwind UI is same-origin anyway);
# production should pin CORS_ALLOWED_ORIGINS to the real frontend origin(s).
CORS_ALLOW_ALL_ORIGINS = DEBUG and not CORS_ALLOWED_ORIGINS

# Default primary key field type
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- barkAI application settings ------------------------------------------
# Groq key for the future real agent. Empty -> chat/services mock is used.
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
