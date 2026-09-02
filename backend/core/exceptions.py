"""DRF error shape.

Session authentication answers "you are not signed in" and "you are signed in
but may not do this" with the SAME 403 status, because there is no browser
auth challenge to issue. The client could only tell them apart by matching on
English prose, so it did not try — and an expired session showed up as
"Authentication credentials were not provided." printed inside whichever panel
happened to ask for data, under the user's own name in the corner.

A PM read that as losing access to attendance (owner 2026-09-02). Every error
now carries a machine-readable `code`, so the app can send an expired session
back to the sign-in screen and leave a real permission refusal where it is.
"""
from rest_framework.views import exception_handler as drf_exception_handler


def exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    if response is None:
        return None
    code = getattr(exc, "default_code", None)
    detail = getattr(exc, "detail", None)
    # DRF hangs the specific code off the detail string itself; it is more
    # precise than the exception class default (authentication_failed vs
    # not_authenticated, permission_denied vs throttled).
    specific = getattr(detail, "code", None)
    if isinstance(specific, str):
        code = specific
    if code and isinstance(response.data, dict):
        response.data.setdefault("code", code)
    return response
