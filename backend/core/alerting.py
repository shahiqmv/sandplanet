"""Error alerting — the server tells us it broke, instead of a user telling us.

Until now a production failure was only visible in the container's stdout, so
we learned about it when somebody said "it isn't working" (conformance audit
2026-08-28; owner asked for alerts 2026-08-29).

Django's own AdminEmailHandler is unthrottled, and one broken page hit by a
dozen users produces a dozen identical emails — which is how alerting gets
muted and then ignored. This throttles by error signature and reports how many
occurrences were folded into each message.
"""
import logging
import threading
import time

from django.utils.log import AdminEmailHandler

WINDOW_SECONDS = 15 * 60

_lock = threading.Lock()
_seen = {}                      # signature -> [first_sent_at, suppressed]


def _signature(record):
    """What counts as 'the same error' — the site of the failure and its type,
    not the message, so per-request detail (a ref, an id) doesn't defeat it."""
    exc_type = ""
    if record.exc_info and record.exc_info[0] is not None:
        exc_type = record.exc_info[0].__name__
    return f"{record.name}:{record.pathname}:{record.lineno}:{exc_type}"


class ThrottledAdminEmailHandler(AdminEmailHandler):
    def emit(self, record):
        sig = _signature(record)
        now = time.monotonic()
        with _lock:
            entry = _seen.get(sig)
            if entry and now - entry[0] < WINDOW_SECONDS:
                entry[1] += 1
                return                      # inside the window — fold it in
            suppressed = entry[1] if entry else 0
            _seen[sig] = [now, 0]
            # Keep the table from growing without bound on a long-running
            # process: drop signatures whose window has long passed.
            if len(_seen) > 500:
                for k, v in list(_seen.items()):
                    if now - v[0] > WINDOW_SECONDS * 4:
                        _seen.pop(k, None)
        if suppressed:
            try:
                record.msg = (f"{record.getMessage()}\n\n"
                              f"[{suppressed} further occurrence(s) of this "
                              f"error were suppressed in the last "
                              f"{WINDOW_SECONDS // 60} minutes]")
                record.args = ()
            except Exception:               # pragma: no cover - defensive
                pass
        try:
            super().emit(record)
        except Exception:                   # pragma: no cover - never recurse
            logging.getLogger(__name__).warning(
                "could not send the error alert", exc_info=False)
