"""Stream a database dump from stdin to off-server object storage.

The dump itself is taken by the host script (deploy/backup.sh) using the
Postgres container's own pg_dump; this command only carries it off the
droplet, because a backup that lives on the machine it protects is not a
backup (conformance audit, 2026-08-28).

    ... | docker compose exec -T web python manage.py backup_upload \
              --name planet-20260828-0200.sql.gz

Also prunes old off-server copies, so the bucket cannot grow without bound.
"""
import sys
from datetime import datetime, timedelta, timezone

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

PREFIX = "backups/"


class Command(BaseCommand):
    help = "Upload a database dump (stdin) to object storage and prune old ones."

    def add_arguments(self, parser):
        parser.add_argument("--name", required=True,
                            help="Object name, e.g. planet-20260828-0200.sql.gz")
        parser.add_argument("--keep-days", type=int, default=35,
                            help="Delete off-server copies older than this.")

    def _client(self):
        try:
            import boto3
        except ImportError:                       # pragma: no cover
            raise CommandError("boto3 is not installed in this image.")
        opts = ((getattr(settings, "STORAGES", {}) or {})
                .get("default", {}).get("OPTIONS") or {})
        if not opts.get("endpoint_url"):
            raise CommandError(
                "Object storage is not configured (S3_ENDPOINT_URL unset) — "
                "the dump stays on the droplet only, which the audit calls a "
                "critical gap. Set the S3_* variables and re-run.")
        return boto3.client(
            "s3", endpoint_url=opts["endpoint_url"],
            aws_access_key_id=opts.get("access_key"),
            aws_secret_access_key=opts.get("secret_key"),
            region_name=opts.get("region_name")), opts["bucket_name"]

    def handle(self, *args, **o):
        client, bucket = self._client()
        blob = sys.stdin.buffer.read()
        if not blob:
            raise CommandError("Nothing on stdin — the dump is empty.")
        if len(blob) < 1024:
            raise CommandError(
                f"The dump is only {len(blob)} bytes — refusing to store a "
                "backup that cannot be real.")
        key = PREFIX + o["name"]
        client.put_object(Bucket=bucket, Key=key, Body=blob,
                          ContentType="application/gzip")
        self.stdout.write(self.style.SUCCESS(
            f"uploaded {key} ({len(blob) / 1048576:.1f} MB)"))

        cutoff = datetime.now(timezone.utc) - timedelta(days=o["keep_days"])
        pruned = 0
        token = None
        while True:
            kw = {"Bucket": bucket, "Prefix": PREFIX}
            if token:
                kw["ContinuationToken"] = token
            page = client.list_objects_v2(**kw)
            for obj in page.get("Contents", []):
                if obj["Key"] != key and obj["LastModified"] < cutoff:
                    client.delete_object(Bucket=bucket, Key=obj["Key"])
                    pruned += 1
            token = page.get("NextContinuationToken")
            if not page.get("IsTruncated"):
                break
        self.stdout.write(f"pruned {pruned} copy(ies) older than "
                          f"{o['keep_days']} days")
