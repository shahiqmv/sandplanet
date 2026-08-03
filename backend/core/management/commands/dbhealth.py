"""One-shot health report for the database + host — run it on the droplet
whenever the app feels slow or you just want to check things are fine.

    docker compose -f docker-compose.prod.yml exec web python manage.py dbhealth

Read-only: it only SELECTs and reads disk stats, never writes. Works on both
the production Postgres and the local SQLite dev database.

    python manage.py dbhealth            # human-readable report
    python manage.py dbhealth --json     # machine-readable (for cron/alerts)
    python manage.py dbhealth --top 25   # show more tables in the size list
"""
import json
import os
import shutil
import time

from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import connection


def _fmt_bytes(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:,.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024


class Command(BaseCommand):
    help = "Report database + host health (connectivity, size, tables, disk)."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true",
                            help="Emit the report as JSON instead of text.")
        parser.add_argument("--top", type=int, default=15,
                            help="How many biggest tables to list (default 15).")

    def handle(self, *args, **opts):
        report = {"warnings": []}

        # --- connectivity + round-trip latency --------------------------------
        t0 = time.perf_counter()
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        report["ping_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        report["engine"] = connection.vendor
        report["version"] = self._db_version()

        # --- database size ----------------------------------------------------
        report["db_size_bytes"] = self._db_size()

        # --- connections (Postgres only) --------------------------------------
        report["connections"] = self._connections(report)

        # --- migrations -------------------------------------------------------
        report["pending_migrations"] = self._pending_migrations()
        if report["pending_migrations"]:
            report["warnings"].append(
                f"{len(report['pending_migrations'])} unapplied migration(s) "
                "— run `manage.py migrate`.")

        # --- biggest tables by row count --------------------------------------
        report["tables"] = self._table_counts(opts["top"])

        # --- host disk (a full disk is the #1 thing that kills Postgres) ------
        usage = shutil.disk_usage(os.getcwd())
        pct = usage.used / usage.total * 100 if usage.total else 0
        report["disk"] = {"total_bytes": usage.total, "free_bytes": usage.free,
                          "used_pct": round(pct, 1)}
        if pct >= 90:
            report["warnings"].append(
                f"Disk {pct:.0f}% full — free space urgently.")
        elif pct >= 80:
            report["warnings"].append(f"Disk {pct:.0f}% full — keep an eye on it.")

        if opts["json"]:
            self.stdout.write(json.dumps(report, indent=2, default=str))
        else:
            self._print(report, opts["top"])

    # ---- collectors ---------------------------------------------------------

    def _db_version(self):
        try:
            with connection.cursor() as cur:
                if connection.vendor == "postgresql":
                    cur.execute("SHOW server_version")
                    return cur.fetchone()[0]
                if connection.vendor == "sqlite":
                    cur.execute("SELECT sqlite_version()")
                    return "SQLite " + cur.fetchone()[0]
        except Exception:
            pass
        return "unknown"

    def _db_size(self):
        try:
            with connection.cursor() as cur:
                if connection.vendor == "postgresql":
                    cur.execute("SELECT pg_database_size(current_database())")
                    return cur.fetchone()[0]
                if connection.vendor == "sqlite":
                    path = connection.settings_dict.get("NAME")
                    return os.path.getsize(path) if path and os.path.exists(path) \
                        else None
        except Exception:
            return None

    def _connections(self, report):
        if connection.vendor != "postgresql":
            return None
        try:
            with connection.cursor() as cur:
                cur.execute("SELECT count(*) FROM pg_stat_activity "
                            "WHERE datname = current_database()")
                active = cur.fetchone()[0]
                cur.execute("SHOW max_connections")
                cap = int(cur.fetchone()[0])
            if cap and active / cap >= 0.8:
                report["warnings"].append(
                    f"{active}/{cap} DB connections in use — nearing the cap.")
            return {"in_use": active, "max": cap}
        except Exception:
            return None

    def _pending_migrations(self):
        try:
            from django.db.migrations.executor import MigrationExecutor
            executor = MigrationExecutor(connection)
            targets = executor.loader.graph.leaf_nodes()
            return [f"{m.app_label}.{m.name}"
                    for m, _backwards in executor.migration_plan(targets)]
        except Exception:
            return []

    def _table_counts(self, top):
        rows = []
        for model in apps.get_models():
            if not model._meta.managed or model._meta.proxy:
                continue
            try:
                rows.append({"table": model._meta.db_table,
                             "label": model._meta.label,
                             "rows": model.objects.count()})
            except Exception:
                continue
        rows.sort(key=lambda r: r["rows"], reverse=True)
        return rows[:top]

    # ---- text rendering -----------------------------------------------------

    def _print(self, r, top):
        ok, warn, err = self.style.SUCCESS, self.style.WARNING, self.style.ERROR
        line = "-" * 58
        self.stdout.write(line)
        self.stdout.write(self.style.MIGRATE_HEADING("  DATABASE HEALTH"))
        self.stdout.write(line)

        ping = r["ping_ms"]
        ping_style = ok if ping < 50 else warn if ping < 250 else err
        self.stdout.write(f"  Engine        {r['engine']}  ({r['version']})")
        self.stdout.write("  Ping          " + ping_style(f"{ping} ms"))
        self.stdout.write(f"  DB size       {_fmt_bytes(r['db_size_bytes'])}")
        if r["connections"]:
            c = r["connections"]
            self.stdout.write(f"  Connections   {c['in_use']} / {c['max']}")
        mig = r["pending_migrations"]
        self.stdout.write("  Migrations    " + (
            ok("up to date") if not mig else warn(f"{len(mig)} pending")))
        d = r["disk"]
        disk_style = ok if d["used_pct"] < 80 else warn if d["used_pct"] < 90 \
            else err
        self.stdout.write("  Disk          " + disk_style(
            f"{d['used_pct']}% used, {_fmt_bytes(d['free_bytes'])} free"))

        self.stdout.write("")
        self.stdout.write(f"  Biggest tables (top {top} by rows)")
        for t in r["tables"]:
            self.stdout.write(f"    {t['rows']:>10,}  {t['label']}")

        self.stdout.write("")
        if r["warnings"]:
            self.stdout.write(err(f"  ! {len(r['warnings'])} warning(s):"))
            for w in r["warnings"]:
                self.stdout.write(err(f"    - {w}"))
        else:
            self.stdout.write(ok("  OK - no problems detected."))
        self.stdout.write(line)
