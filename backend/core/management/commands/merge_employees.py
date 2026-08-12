"""Merge duplicate employee records from a CSV of pairs.

    python manage.py merge_employees pairs.csv            # dry run (default)
    python manage.py merge_employees pairs.csv --apply

CSV: a `source` (or emp_no) column and a `target` (or "MERGE INTO (emp no)")
column; blank targets are skipped. Optional `clash` column per row —
keep_higher (default), keep_target or keep_source.
"""
import csv

from django.core.management.base import BaseCommand, CommandError

from core import employee_merge as em
from core.models import Employee, User

SRC_KEYS = ("source", "emp_no", "from")
TGT_KEYS = ("target", "merge into (emp no)", "merge_into", "into")


def _pick(row, keys):
    for k, v in row.items():
        if (k or "").strip().lower() in keys:
            return (v or "").strip()
    return ""


class Command(BaseCommand):
    help = "Merge duplicate employee records listed in a CSV of pairs."

    def add_arguments(self, parser):
        parser.add_argument("csv_path")
        parser.add_argument("--apply", action="store_true",
                            help="actually merge (default is a dry run)")
        parser.add_argument("--clash", default="keep_higher",
                            choices=("keep_higher", "keep_target",
                                     "keep_source"),
                            help="default rule for a day both records hold")
        parser.add_argument("--actor", default="",
                            help="username to record as the actor")

    def handle(self, *args, **o):
        try:
            rows = list(csv.DictReader(open(o["csv_path"], encoding="utf-8-sig")))
        except OSError as e:
            raise CommandError(str(e))
        actor = (User.objects.filter(username=o["actor"]).first()
                 if o["actor"] else User.objects.filter(role="ADMIN").first())
        pairs, problems = [], []
        for r in rows:
            s, t = _pick(r, SRC_KEYS), _pick(r, TGT_KEYS)
            if not s or not t:
                continue
            src = Employee.objects.filter(emp_no=s).first()
            tgt = Employee.objects.filter(emp_no=t).first()
            if not src or not tgt:
                problems.append(f"{s} -> {t}: "
                                f"{'source' if not src else 'target'} not found")
                continue
            clash = (_pick(r, ("clash",)) or o["clash"]).lower()
            pairs.append((src, tgt, clash))

        if problems:
            self.stderr.write("UNRESOLVED:")
            for p in problems:
                self.stderr.write("   " + p)
        self.stdout.write(f"{len(pairs)} merge(s) to perform"
                          f"{' — DRY RUN' if not o['apply'] else ''}\n")
        total_clashes = 0
        for src, tgt, clash in pairs:
            pv = em.preview(src, tgt)
            moves = ", ".join(f"{k}={v}" for k, v in pv["moves"].items() if v)
            self.stdout.write(
                f"  {src.emp_no} {src.full_name[:26]:26} -> {tgt.emp_no} "
                f"{tgt.full_name[:26]:26} | {moves or 'nothing to move'}")
            if pv["attendance_clashes"]:
                total_clashes += len(pv["attendance_clashes"])
                self.stdout.write(
                    f"      {len(pv['attendance_clashes'])} clashing day(s) "
                    f"— {clash}: "
                    + ", ".join(str(d) for d in pv["attendance_clashes"][:6])
                    + (" …" if len(pv["attendance_clashes"]) > 6 else ""))
            for w in pv["warnings"]:
                self.stdout.write(f"      ⚠ {w}")
            if o["apply"]:
                detail, err = em.merge(src, tgt, actor, clash=clash)
                if err:
                    self.stderr.write(f"      FAILED: {err}")
                else:
                    self.stdout.write("      merged")
        self.stdout.write(f"\ntotal clashing days: {total_clashes}")
        if not o["apply"]:
            self.stdout.write("dry run — nothing changed. Re-run with --apply.")
