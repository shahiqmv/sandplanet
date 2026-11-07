"""Connect Planet to the owner's OneDrive, once (owner 2026-11-07).

    manage.py onedrive_connect /path/to/onedrive-token.txt

The owner ran `rclone authorize onedrive` on their own machine and sent the
file it wrote. This reads the token out of it, asks Microsoft which drive it
is, writes rclone's config, and deletes the token file. Nothing secret is
printed: the token goes from the file into the config and nowhere else.
"""
import json
import os
import re
import urllib.request

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core import drive


class Command(BaseCommand):
    help = "Install the owner's OneDrive authorisation for the time-lapse intake."

    def add_arguments(self, parser):
        parser.add_argument("token_file")

    def handle(self, token_file, **options):
        cfg = getattr(settings, "RCLONE_CONFIG", "")
        if not cfg:
            raise CommandError("RCLONE_CONFIG is not set on this server.")
        try:
            raw = open(token_file).read()
        except OSError as e:
            raise CommandError(f"Cannot read the token file: {e}")
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            raise CommandError("That file holds no token. Run "
                               "`rclone authorize onedrive` again.")
        token = json.loads(m.group(0))
        req = urllib.request.Request(
            "https://graph.microsoft.com/v1.0/me/drive",
            headers={"Authorization": f"Bearer {token['access_token']}"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                info = json.load(r)
        except Exception as e:
            raise CommandError(f"Microsoft did not accept the token: {e}")
        owner = (info.get("owner") or {}).get("user", {}).get("displayName", "")
        os.makedirs(os.path.dirname(cfg), exist_ok=True)
        with open(cfg, "w") as f:
            f.write("[onedrive]\ntype = onedrive\n"
                    f"token = {json.dumps(token)}\n"
                    f"drive_id = {info['id']}\n"
                    f"drive_type = {info.get('driveType', 'personal')}\n")
        os.chmod(cfg, 0o600)
        os.remove(token_file)
        names = sorted(f["name"] for f in drive._list_dirs(""))
        self.stdout.write(f"Connected to {owner or 'the'} OneDrive "
                          f"({info.get('driveType')}). Top-level folders: "
                          + (", ".join(names) or "none") + ".")
