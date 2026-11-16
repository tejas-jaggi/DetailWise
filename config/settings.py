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


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ImproperlyConfigured(f"{name} must be a boolean (True or False).")


def env_int(name: str, default: int, minimum: int = 0, maximum=None) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        raise ImproperlyConfigured(f"{name} must be a whole number.") from None
    if value < minimum or (maximum is not None and value > maximum):
        raise ImproperlyConfigured(f"{name} is outside the allowed range.")
    return value


def env_list(name: str, default: str = "") -> list[str]:
    raw = os.environ.get(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


# Local development keeps .env support. Production can use only injected values.
# Real environment variables always win over the file.
if env_bool("DJANGO_READ_DOT_ENV", default=True):
    load_dotenv(BASE_DIR / ".env", override=False)


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
ALLOWED_HOSTS = env_list(
    "DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1" if DEBUG else ""
)
if not DEBUG and (not ALLOWED_HOSTS or "*" in ALLOWED_HOSTS):
    raise ImproperlyConfigured(
        "DJANGO_ALLOWED_HOSTS must list explicit hosts when DJANGO_DEBUG=False."
    )
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

# HTTPS is required by default outside local development. HSTS is a separate
# deployment decision: first verify HTTPS, then gradually increase its lifetime.
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", default=not DEBUG)
SESSION_COOKIE_SECURE = env_bool("DJANGO_SESSION_COOKIE_SECURE", default=not DEBUG)
CSRF_COOKIE_SECURE = env_bool("DJANGO_CSRF_COOKIE_SECURE", default=not DEBUG)
SECURE_HSTS_SECONDS = env_int("DJANGO_SECURE_HSTS_SECONDS", default=0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS")
SECURE_HSTS_PRELOAD = env_bool("DJANGO_SECURE_HSTS_PRELOAD")

# Enable only behind a trusted, sanitizing proxy with no public route around it.
# See docs/deployment.md. Waitress can instead set wsgi.url_scheme securely.
SECURE_PROXY_SSL_HEADER = (
    ("HTTP_X_FORWARDED_PROTO", "https")
    if env_bool("DJANGO_TRUST_X_FORWARDED_PROTO")
    else None
)


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
    "whitenoise.middleware.WhiteNoiseMiddleware",
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


# SQLite stays the default; PostgreSQL must be selected explicitly. A partial
# PostgreSQL configuration fails at startup instead of falling back to SQLite.
database_engine = os.environ.get("DJANGO_DB_ENGINE", "sqlite").strip().lower()
if database_engine == "sqlite":
    default_database = {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
elif database_engine == "postgresql":
    required_database_vars = (
        "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_HOST"
    )
    missing_database_vars = [
        name for name in required_database_vars if not os.environ.get(name, "").strip()
    ]
    if missing_database_vars:
        raise ImproperlyConfigured(
            "PostgreSQL requires environment variables: " + ", ".join(missing_database_vars)
        )
    database_sslmode = os.environ.get("DJANGO_DB_SSLMODE", "verify-full").strip().lower()
    if database_sslmode not in {
        "disable", "allow", "prefer", "require", "verify-ca", "verify-full"
    }:
        raise ImproperlyConfigured("DJANGO_DB_SSLMODE must be a valid PostgreSQL SSL mode.")
    database_options = {
        "sslmode": database_sslmode,
        "connect_timeout": env_int("DJANGO_DB_CONNECT_TIMEOUT", default=10, minimum=1),
    }
    if os.environ.get("DJANGO_DB_SSLROOTCERT"):
        database_options["sslrootcert"] = os.environ["DJANGO_DB_SSLROOTCERT"]
    default_database = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ["POSTGRES_DB"],
        "USER": os.environ["POSTGRES_USER"],
        "PASSWORD": os.environ["POSTGRES_PASSWORD"],
        "HOST": os.environ["POSTGRES_HOST"],
        "PORT": env_int("POSTGRES_PORT", default=5432, minimum=1, maximum=65535),
        "CONN_MAX_AGE": env_int("DJANGO_DB_CONN_MAX_AGE", default=60),
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": database_options,
    }
else:
    raise ImproperlyConfigured("DJANGO_DB_ENGINE must be sqlite or postgresql.")

DATABASES = {"default": default_database}


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
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        ),
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# Weather guidance (Open-Meteo forecast and optional local AI explanation)

GUIDANCE = guidance_settings(os.environ)


def guidance_rate_limit_settings(environ) -> dict:
    """Positive integer limits; invalid deployment configuration fails startup."""
    values = {}
    for key, variable, default in (
        ("REQUESTS", "GUIDANCE_EXPLAIN_LIMIT", "5"),
        ("WINDOW_SECONDS", "GUIDANCE_EXPLAIN_WINDOW_SECONDS", "600"),
    ):
        raw = (environ.get(variable) or default).strip()
        try:
            value = int(raw)
        except (TypeError, ValueError):
            raise ImproperlyConfigured(f"{variable} must be a positive integer.") from None
        if value < 1:
            raise ImproperlyConfigured(f"{variable} must be a positive integer.")
        values[key] = value
    return values


GUIDANCE_RATE_LIMIT = guidance_rate_limit_settings(os.environ)
