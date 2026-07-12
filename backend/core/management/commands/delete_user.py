"""Find and delete a user account from the shell — for cleaning up mistakes
such as a duplicate account that can't be removed through the UI.

    # 1. Look first — lists every account matching the name (case-insensitive)
    python manage.py delete_user pubudu

    # 2. Delete the exact one you meant, by its id (shown in step 1)
    python manage.py delete_user --id 42
    python manage.py delete_user --id 42 --yes     # skip the confirmation

Deletion is refused if the account owns protected records (documents,
approvals, payments) — deactivate that one instead. Always run the name
lookup first so you delete the right id: two accounts like "pubudu" and
"Pubudu" look identical at a glance but have different ids.
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db.models import ProtectedError

User = get_user_model()


class Command(BaseCommand):
    help = "List users matching a name, or delete one by id."

    def add_arguments(self, parser):
        parser.add_argument("username", nargs="?",
                            help="Name to search for (case-insensitive).")
        parser.add_argument("--id", type=int,
                            help="Id of the user to delete.")
        parser.add_argument("--yes", action="store_true",
                            help="Skip the delete confirmation prompt.")

    def handle(self, *args, **opts):
        if opts.get("id"):
            self._delete(opts["id"], opts["yes"])
            return
        name = opts.get("username")
        if not name:
            raise CommandError(
                "Give a username to search for, or --id <n> to delete.")
        self._list(name)

    def _list(self, name):
        rows = User.objects.filter(username__icontains=name).order_by(
            "username", "id")
        if not rows:
            self.stdout.write(f"No users match '{name}'.")
            return
        self.stdout.write(f"{len(rows)} user(s) matching '{name}':\n")
        for u in rows:
            active = "active" if u.is_active else "DEACTIVATED"
            last = u.last_login.strftime("%Y-%m-%d") if u.last_login else "never"
            joined = u.date_joined.strftime("%Y-%m-%d") if u.date_joined else "?"
            self.stdout.write(
                f"  id={u.id:<4} {u.username:<18} {active:<11} "
                f"role={u.role:<14} joined={joined}  last-login={last}")
        self.stdout.write(
            "\nDelete the right one with:  "
            "python manage.py delete_user --id <id>")

    def _delete(self, user_id, assume_yes):
        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            raise CommandError(f"No user with id {user_id}.")
        label = f"id={user.id} username='{user.username}' role={user.role}"
        if not assume_yes:
            answer = input(f"Permanently delete {label}? [y/N] ").strip().lower()
            if answer not in ("y", "yes"):
                self.stdout.write("Cancelled.")
                return
        try:
            user.delete()
        except ProtectedError:
            raise CommandError(
                f"Can't delete {label}: it owns records (documents, approvals, "
                "payments). Deactivate it instead.")
        self.stdout.write(self.style.SUCCESS(f"Deleted {label}."))
