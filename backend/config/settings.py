"""
Django settings — Sand Planet Site Documents.

Environment-driven per SP_Technical_Design.md §5:
Postgres + MinIO/Spaces when configured; SQLite fallback for local dev
without Docker (see DECISIONS.md D1).
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY", "insecure-local-dev-key-change-in-staging"
)
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
# Dev default "*" lets the team-review tunnel (trycloudflare.com) reach the
# dev server; production always sets DJANGO_ALLOWED_HOSTS explicitly.
ALLOWED_HOSTS = os.environ.get(
    "DJANGO_ALLOWED_HOSTS", "*" if DEBUG else "localhost,127.0.0.1"
).split(",")

# Vite dev server proxies /api same-origin in production builds; in dev the
# browser origin is the Vite port, so trust it explicitly — plus the
# Cloudflare quick-tunnel domain used for team review links (dev only).
CSRF_TRUSTED_ORIGINS = os.environ.get(
    "CSRF_TRUSTED_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173,"
    "https://*.trycloudflare.com" if DEBUG else "",
).split(",") if (os.environ.get("CSRF_TRUSTED_ORIGINS") or DEBUG) else []

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "core",
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
        # frontend/dist lets Django serve the built SPA (same origin, design §1)
        "DIRS": [BASE_DIR.parent / "frontend" / "dist", BASE_DIR / "pdf_templates"],
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

if os.environ.get("POSTGRES_HOST"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "HOST": os.environ["POSTGRES_HOST"],
            "PORT": os.environ.get("POSTGRES_PORT", "5432"),
            "NAME": os.environ.get("POSTGRES_DB", "sandplanet"),
            "USER": os.environ.get("POSTGRES_USER", "sandplanet"),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
        }
    }
else:  # DECISIONS.md D1 — local dev without Docker only
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# Argon2 first, per design §1
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

AUTH_USER_MODEL = "core.User"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"  # stored UTC; UI displays Maldives UTC+5 (design §1)
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Files: Spaces/MinIO when configured (design §1); local-disk fallback for
# dev without Docker only (DECISIONS.md D3). Production must set S3_* env.
if os.environ.get("S3_ENDPOINT_URL"):
    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3.S3Storage",
            "OPTIONS": {
                "endpoint_url": os.environ["S3_ENDPOINT_URL"],
                "access_key": os.environ.get("S3_ACCESS_KEY"),
                "secret_key": os.environ.get("S3_SECRET_KEY"),
                "bucket_name": os.environ.get("S3_BUCKET", "sandplanet-local"),
            },
        },
        # Compression only, no manifest re-hashing — Vite already
        # content-hashes its bundles, and the manifest post-processor trips
        # over Vite's asset references during collectstatic.
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"
        },
    }
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# PDFs block issue when true (staging/production); local dev may lack the
# WeasyPrint GTK libraries (DECISIONS.md D4).
PDF_REQUIRED = os.environ.get("PDF_REQUIRED", "0") == "1"
# Built SPA assets: vite builds with --base=/static/ so index.html points
# at /static/assets/*; the prefixed entry maps them there.
STATICFILES_DIRS = (
    [("assets", BASE_DIR.parent / "frontend" / "dist" / "assets")]
    if (BASE_DIR.parent / "frontend" / "dist" / "assets").exists()
    else []
)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---- Production hardening (M8) ------------------------------------------
# Applied whenever DEBUG is off. The app runs behind a TLS-terminating
# reverse proxy (Caddy/nginx/platform LB) that sets X-Forwarded-Proto.
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    # Redirect http→https at the app unless the proxy already does it
    SECURE_SSL_REDIRECT = os.environ.get("SECURE_SSL_REDIRECT", "1") == "1"
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    # HSTS: opt-in via env (only once HTTPS is confirmed working on the
    # domain, to avoid locking browsers onto a broken cert)
    SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "0"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = SECURE_HSTS_SECONDS > 0
    SECURE_HSTS_PRELOAD = SECURE_HSTS_SECONDS > 0
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"
