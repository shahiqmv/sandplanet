"""
Django settings — Sand Planet Site Documents.

Environment-driven per SP_Technical_Design.md §5:
Postgres + MinIO/Spaces when configured; SQLite fallback for local dev
without Docker (see DECISIONS.md D1).
"""

import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY", "insecure-local-dev-key-change-in-staging"
)
# Off unless somebody turns it on. The old default was ON, so a box that lost
# its .env would have shown every visitor the settings and the traceback
# (owner 2026-09-02). Local dev sets DJANGO_DEBUG=1 (see .claude/launch.json).
DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"

# --- Shipment tracking (ShipsGo, D40). Secrets set in platform env, never here.
SHIPSGO_BASE_URL = os.environ.get("SHIPSGO_BASE_URL",
                                  "https://api.shipsgo.com/v2")
SHIPSGO_API_KEY = os.environ.get("SHIPSGO_API_KEY", "")
SHIPSGO_WEBHOOK_SECRET = os.environ.get("SHIPSGO_WEBHOOK_SECRET", "")

# --- Local vessel tracking (FollowMe, owner 2026-08-07). Key set in platform
# env, never here. The key is part of the URL path in this provider's API.
FOLLOWME_BASE_URL = os.environ.get("FOLLOWME_BASE_URL",
                                   "https://followme.mv/api/v5")
FOLLOWME_API_KEY = os.environ.get("FOLLOWME_API_KEY", "")
TRACKING_ETA_SLIP_HOURS = int(os.environ.get("TRACKING_ETA_SLIP_HOURS", "24"))
TRACKING_CREDIT_FLOOR = int(os.environ.get("TRACKING_CREDIT_FLOOR", "10"))

# --- Site cameras (owner 2026-08-12). CAMERA_RELAY_URL is the PUBLIC origin a
# browser fetches WebRTC/WHEP from; CAMERA_RELAY_API is the MediaMTX control
# API, which must stay on loopback. Empty relay URL = cameras disabled, which
# is the correct state for any deployment without a relay.
# In production this is a PATH ("/cams"), not an origin: Caddy proxies it to
# the relay on whichever host the page was served from, so the staff app and
# the client portal each fetch their own origin and there is no CORS at all.
CAMERA_RELAY_URL = os.environ.get(
    "CAMERA_RELAY_URL", "http://127.0.0.1:8889" if DEBUG else "")
CAMERA_RELAY_API = os.environ.get("CAMERA_RELAY_API", "http://127.0.0.1:9997")
# Shared secret the relay puts in its auth-hook URL. Empty = the hook is dead,
# which is the right default: a missing secret must never mean "allow". The
# DEBUG fallback exists only so a local relay can be pointed at a dev server.
CAMERA_RELAY_SECRET = os.environ.get(
    "CAMERA_RELAY_SECRET", "dev-relay-secret" if DEBUG else "")
# Dev default "*" lets the team-review tunnel (trycloudflare.com) reach the
# dev server; production always sets DJANGO_ALLOWED_HOSTS explicitly.
ALLOWED_HOSTS = os.environ.get(
    "DJANGO_ALLOWED_HOSTS", "*" if DEBUG else "localhost,127.0.0.1"
).split(",")
# The camera relay calls the auth hook container-to-container as
# http://web:8000/…, so the Host header is the compose service name and Django
# would answer DisallowedHost (400) — which MediaMTX reports only as "failed to
# authenticate", sending you looking for a credential bug that isn't there.
# Nothing outside the compose network can present this Host: Caddy always
# forwards the real domain.
if "*" not in ALLOWED_HOSTS and "web" not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append("web")

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
    # Session auth cannot use 401, so "not signed in" and "not allowed" are
    # both 403. The handler tags every error with a code so the client can
    # tell them apart without reading English.
    "EXCEPTION_HANDLER": "core.exceptions.exception_handler",
    # JSON only. A site PM landed on DRF's browsable HTML page for a payroll
    # line — a form-filled developer view with the company's name on it —
    # because a browser navigated to an API URL (owner 2026-09-02). The API
    # is for the app; nobody should ever see it rendered.
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
}

# Shared secret in the biometric terminals' push URL. Set in the environment;
# empty means the ADMS endpoints refuse everything, which is the right default
# for a machine with no terminals (owner 2026-08-23).
ADMS_SECRET = os.environ.get("ADMS_SECRET", "")

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"  # stored UTC; UI displays Maldives UTC+5 (design §1)
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Files: Spaces/MinIO when configured (design §1); local-disk fallback for
# dev without Docker only (DECISIONS.md D3). Production must set S3_* env.
if os.environ.get("S3_ENDPOINT_URL"):
    import re as _re

    # SigV4 needs a region; DigitalOcean Spaces derives it from the endpoint
    # subdomain (e.g. https://sgp1.digitaloceanspaces.com -> "sgp1").
    _s3_region = os.environ.get("S3_REGION")
    if not _s3_region:
        _m = _re.match(r"https?://([^.]+)\.", os.environ["S3_ENDPOINT_URL"])
        _s3_region = _m.group(1) if _m else "us-east-1"
    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3.S3Storage",
            "OPTIONS": {
                "endpoint_url": os.environ["S3_ENDPOINT_URL"],
                "access_key": os.environ.get("S3_ACCESS_KEY"),
                "secret_key": os.environ.get("S3_SECRET_KEY"),
                "bucket_name": os.environ.get("S3_BUCKET", "sandplanet-local"),
                "region_name": _s3_region,
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

# Logging. There was no LOGGING block at all until the conformance audit
# (2026-08-28): unhandled exceptions went to gunicorn's stdout unlabelled and
# swallowed notification failures were invisible. Console handler only — the
# platform captures container stdout — but now every error carries its
# traceback, logger name and timestamp.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(asctime)s %(levelname)s %(name)s: %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
        },
        # Emails whoever is in ERROR_ALERT_TO when the server breaks. Silent
        # when that is unset (dev, tests) because ADMINS is then empty.
        "mail_admins": {
            "class": "core.alerting.ThrottledAdminEmailHandler",
            "level": "ERROR",
            "include_html": False,
        },
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        # 500s with the traceback, which Django otherwise only emails.
        "django.request": {"handlers": ["console", "mail_admins"],
                           "level": "ERROR", "propagate": False},
        "django.security": {"handlers": ["console"], "level": "WARNING",
                            "propagate": False},
        # Our own modules log at INFO; SQL stays off. Anything we log at
        # ERROR — a failed push, a swallowed integration failure — alerts too.
        "core": {"handlers": ["console", "mail_admins"], "level": "INFO",
                 "propagate": False},
        "django.db.backends": {"level": "WARNING"},
        # WeasyPrint and fontTools narrate every glyph they subset at INFO —
        # hundreds of lines per PDF in the container log (2026-09-03).
        "weasyprint": {"level": "WARNING"},
        "fontTools": {"level": "WARNING"},
    },
}

# Who hears about a server error. Comma-separated addresses; unset = nobody,
# which is the dev and test default (owner 2026-08-29).
ADMINS = [("Planet alerts", a.strip())
          for a in os.environ.get("ERROR_ALERT_TO", "").split(",") if a.strip()]

# Email (SMTP) — set EMAIL_HOST etc. in production (e.g. Zoho:
# smtp.zoho.com, port 465, SSL, an app-specific password). Without it, dev
# prints emails to the console instead of sending.
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
if EMAIL_HOST:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "465"))
    EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
    EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
    EMAIL_USE_SSL = os.environ.get("EMAIL_USE_SSL", "1") == "1"
    EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "0") == "1"
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL = os.environ.get(
    "DEFAULT_FROM_EMAIL", os.environ.get("EMAIL_HOST_USER",
                                         "no-reply@sandplanet.mv"))
# Error alerts send From here (Django's own setting for server messages).
SERVER_EMAIL = os.environ.get("SERVER_EMAIL", DEFAULT_FROM_EMAIL)

# App emails send From DEFAULT_FROM_EMAIL with the acting user's name + a
# Reply-To to that user; a reply with no user routes to this office inbox.
REPLY_TO_FALLBACK = os.environ.get("REPLY_TO_FALLBACK", DEFAULT_FROM_EMAIL)
# The projects office is copied on every shipping-document share to the
# clearing agent (owner 2026-08-24).
IMPORT_SHARE_CC = os.environ.get("IMPORT_SHARE_CC", "projects@sandplanet.mv")
# The login link put in invite emails.
APP_BASE_URL = os.environ.get(
    "APP_BASE_URL", "https://sandplanet.159.223.35.180.sslip.io")
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
#
# Not during `manage.py test`: the test client speaks plain HTTP, and with
# DEBUG now off by default the https redirect answered every API test with a
# 301 page (owner 2026-09-02). Production sets DJANGO_DEBUG explicitly and is
# unaffected; the deploy gate (check --deploy) still sees the real values.
TESTING = len(sys.argv) > 1 and sys.argv[1] == "test"
if not DEBUG and not TESTING:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    # Redirect http→https at the app unless the proxy already does it
    SECURE_SSL_REDIRECT = os.environ.get("SECURE_SSL_REDIRECT", "1") == "1"
    # …but never for the camera relay's auth hook. That call is
    # container-to-container plain HTTP and cannot be upgraded: the only TLS
    # certificate we hold is for the public domain, and MediaMTX does not
    # follow the redirect — it just reports "failed to authenticate". The path
    # is not routable from the internet (Caddy 404s /api/relay/*), so nothing
    # is exposed by exempting it.
    SECURE_REDIRECT_EXEMPT = [r"^api/relay/"]
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    # A system holding passports and payroll should not keep a session alive
    # for Django's default two weeks (audit 2026-08-28). Twelve hours covers
    # a site day; the clock restarts on each request.
    SESSION_COOKIE_AGE = int(os.environ.get("SESSION_COOKIE_AGE", 12 * 3600))
    SESSION_SAVE_EVERY_REQUEST = True
    # HSTS: opt-in via env (only once HTTPS is confirmed working on the
    # domain, to avoid locking browsers onto a broken cert)
    SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "0"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = SECURE_HSTS_SECONDS > 0
    SECURE_HSTS_PRELOAD = SECURE_HSTS_SECONDS > 0
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"
