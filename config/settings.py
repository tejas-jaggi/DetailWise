"""
Django settings for the DetailWise project.

Secrets and machine-specific values come from environment variables, loaded
from a local `.env` file during development (see `.env.example`).
"""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env from the project root if it exists. Real environment variables win.
load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    raw = os.environ.get(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def guidance_settings(environ) -> dict:
    """Settings for weather guidance. Only the local Ollama values can be overridden.

    A blank environment value means "use the default".
    """

    def text(name: str, default: str) -> str:
        return (environ.get(name) or "").strip() or default

    raw_timeout = text("GUIDANCE_LLM_TIMEOUT", "45")
    if not raw_timeout.isdigit() or int(raw_timeout) < 1:
        raise ImproperlyConfigured(
            "GUIDANCE_LLM_TIMEOUT must be a whole number of seconds (1 or more)."
        )

    return {
        # Fixed shop location: Urbana, IL. All forecast dates and hours are Central Time.
        "LATITUDE": 40.11,
        "LONGITUDE": -88.21,
        "TIMEZONE": "America/Chicago",
        "FORECAST_URL": "https://api.open-meteo.com/v1/forecast",
        "FORECAST_DAYS": 16,
        "WEATHER_TIMEOUT": 5,
        "CACHE_SECONDS": 30 * 60,
        # Local AI model (Ollama). No API key and no hosted provider.
        "OLLAMA_BASE_URL": text("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
        "OLLAMA_MODEL": text("OLLAMA_MODEL", "llama3"),
        "LLM_TIMEOUT": int(raw_timeout),
    }


SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY is not set. Copy .env.example to .env and generate a key "
        "(see README.md)."
    )

DEBUG = env_bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")


# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # DetailWise apps
    "accounts",
    "bookings",
    "guidance",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
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

WSGI_APPLICATION = "config.wsgi.application"


# Database: SQLite for local development. Postgres comes with deployment.

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}


# Authentication

AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "bookings:my_bookings"
LOGOUT_REDIRECT_URL = "bookings:catalog"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 8},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# Internationalization: the shop operates in Urbana, IL (Central Time).

LANGUAGE_CODE = "en-us"
TIME_ZONE = "America/Chicago"
USE_I18N = True
USE_TZ = True


# Static files

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# Weather guidance (Open-Meteo forecast and optional local AI explanation)

GUIDANCE = guidance_settings(os.environ)
