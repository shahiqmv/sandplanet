"""Connect Planet to the owner's OneDrive, once (owner 2026-11-07).

    manage.py onedrive_connect /path/to/onedrive-token.txt

The owner ran `rclone authorize onedrive` on their own machine and sent the
file it wrote. This writes rclone's config from it, lets rclone renew the
access (the file is usually more than an hour old by the time it arrives,
and an access key lasts an hour; the renewal key does not), asks Microsoft
which drive it is, completes the config, and deletes the token file.
Nothing secret is printed: the token goes from the file into the config and
nowhere else.
"""
import json
import os
import re
import urllib.request

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core import drive


def _write(cfg, token, drive_id="", drive_type="personal"):
    os.makedirs(os.path.dirname(cfg), exist_ok=True)
    with open(cfg, "w") as f:
        f.write("[onedrive]\ntype = onedrive\n"
                f"token = {json.dumps(token)}\n"
                f"drive_id = {drive_id}\n"
                f"drive_type = {drive_type}\n")
    os.chmod(cfg, 0o600)


def _read_token(cfg):
    for line in open(cfg):
        if line.startswith("token = "):
            return json.loads(line[len("token = "):])
    return None


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
        # A placeholder drive so rclone makes one request: it renews the
        # access key first and writes the renewed token back to the config.
        _write(cfg, token, drive_id="pending")
        drive._run(["lsjson", "onedrive:"], 60)
        token = _read_token(cfg) or token
        req = urllib.request.Request(
            "https://graph.microsoft.com/v1.0/me/drive",
            headers={"Authorization": f"Bearer {token['access_token']}"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                info = json.load(r)
        except Exception as e:
            os.remove(cfg)
            raise CommandError(f"Microsoft did not accept the token: {e}. "
                               "Sign in again and send a fresh file.")
        owner = (info.get("owner") or {}).get("user", {}).get("displayName", "")
        _write(cfg, token, info["id"], info.get("driveType", "personal"))
        os.remove(token_file)
        names = sorted(f["name"] for f in drive._list_dirs(""))
        self.stdout.write(f"Connected to {owner or 'the'} OneDrive "
                          f"({info.get('driveType')}). Top-level folders: "
                          + (", ".join(names) or "none") + ".")
