"""Fold a duplicate supplier into the record it copies.

    python manage.py merge_supplier --from 149 --into 50 --actor admin \
        --reason "same company" [--commit]

Without --commit it is a dry run: the merge runs inside a transaction that
is rolled back, and prints what would move."""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core import suppliers
from core.models import Supplier, User


class _Rollback(Exception):
    pass


class Command(BaseCommand):
    help = "Merge a duplicate supplier into the record it copies."

    def add_arguments(self, parser):
        parser.add_argument("--from", dest="dup", type=int, required=True)
        parser.add_argument("--into", type=int, required=True)
        parser.add_argument("--actor", required=True)
        parser.add_argument("--reason", default="")
        parser.add_argument("--commit", action="store_true")

    def handle(self, *args, **o):
        try:
            dup = Supplier.objects.get(pk=o["dup"])
            into = Supplier.objects.get(pk=o["into"])
            actor = User.objects.get(username=o["actor"])
        except (Supplier.DoesNotExist, User.DoesNotExist) as e:
            raise CommandError(str(e)) from None
        self.stdout.write(f"{dup.pk} {dup.name}  ->  {into.pk} {into.name}")
        self.stdout.write(f"  uses before: copy {suppliers.usage(dup)} | "
                          f"kept {suppliers.usage(into)}")
        try:
            with transaction.atomic():
                moved, err = suppliers.merge(dup, into, actor, o["reason"])
                if err:
                    raise CommandError(err)
                dup.refresh_from_db()
                into.refresh_from_db()
                assert not suppliers.usage(dup), suppliers.usage(dup)
                assert not dup.is_active
                self.stdout.write(f"  moved {moved}")
                self.stdout.write(f"  kept now: {suppliers.usage(into)} | "
                                  f"trading={into.is_trading}")
                if not o["commit"]:
                    raise _Rollback()
        except _Rollback:
            self.stdout.write("DRY RUN — rolled back")
            return
        self.stdout.write("COMMITTED")
