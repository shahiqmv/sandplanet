"""Throwaway settings for the user-guide screenshot instance.

Runs a SECOND, fully isolated Django on its own SQLite file and media
directory so seeding demo data can NEVER touch the live team-review server
(the :8000 process on db.sqlite3 exposed through the cloudflared tunnel).

Usage (always pass --settings):
    python manage.py migrate      --settings=config.settings_demo
    python manage.py seed         --settings=config.settings_demo
    python manage.py seed_demo    --settings=config.settings_demo
    python manage.py runserver 127.0.0.1:8001 --settings=config.settings_demo

Everything else (SQLite engine, DEBUG, WhiteNoise, PDF libs) is inherited
from the real settings unchanged — only the DB file and MEDIA_ROOT move.
"""

from .settings import *  # noqa: F401,F403 — inherit the full dev config

# Separate database file — the live server keeps db.sqlite3; we use this.
DATABASES["default"]["ENGINE"] = "django.db.backends.sqlite3"  # noqa: F405
DATABASES["default"]["NAME"] = BASE_DIR / "db.demo.sqlite3"    # noqa: F405
# Drop any Postgres keys that may have been set if POSTGRES_HOST is exported,
# so the demo instance is always the self-contained SQLite file above.
for _k in ("HOST", "PORT", "USER", "PASSWORD"):
    DATABASES["default"].pop(_k, None)  # noqa: F405

# Separate media tree — demo uploads (DPR photos, receipts, generated PDFs)
# never mingle with the live server's media/.
MEDIA_ROOT = BASE_DIR / "media-demo"  # noqa: F405

# The guide must show real generated PDFs, so require WeasyPrint to succeed
# on issue rather than silently skipping the PDF (the live dev default is 0).
PDF_REQUIRED = True
