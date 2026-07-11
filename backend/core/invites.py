"""Send a new user their login details (username, temporary password, link).

Uses Django's configured email backend (SMTP in production, console in dev),
so nothing sends until EMAIL_HOST is set. The temporary password is emailed
once and must be changed on first login.
"""
import secrets
import string

from django.conf import settings
from django.core.mail import send_mail

_ALPHABET = string.ascii_letters + string.digits


def make_temp_password(length=10):
    """A readable random password (letters+digits, no ambiguous chars)."""
    pool = _ALPHABET.translate(str.maketrans("", "", "O0Il1"))
    return "".join(secrets.choice(pool) for _ in range(length))


def send_user_invite(user, temp_password):
    """Email the user their credentials + the login link. Returns True if the
    send was attempted (an email address is present)."""
    if not user.email:
        return False
    link = settings.APP_BASE_URL
    subject = "Your Sand Planet Project Management login"
    body = (
        f"Hello {user.full_name or user.username},\n\n"
        "An account has been created for you on the Sand Planet Project "
        "Management app.\n\n"
        f"    Login page : {link}\n"
        f"    Username   : {user.username}\n"
        f"    Password   : {temp_password}\n\n"
        "For your security, you'll be asked to set your own password the "
        "first time you sign in.\n\n"
        "If you weren't expecting this, please contact your administrator.\n\n"
        "— Sand Planet Pvt Ltd"
    )
    send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [user.email],
              fail_silently=False)
    return True
