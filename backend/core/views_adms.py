"""The endpoints a biometric terminal talks to (ZKTeco ADMS / push protocol).

These are NOT part of the session-authenticated API: a gate terminal cannot log
in or set an auth header. It proves itself two ways — a shared secret in the
path, which Caddy is the only route to, and a serial number that must already be
registered against a site. Anything else is refused and logged, never stored as
attendance.

The device calls, we never call it: nothing has to be opened up on the site
network, no fixed IP, no port forwarding.
"""
import logging

from django.conf import settings
from django.http import HttpResponse, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt

from . import biometric as svc

log = logging.getLogger(__name__)


def _secret_ok(secret):
    want = getattr(settings, "ADMS_SECRET", "") or ""
    return bool(want) and secret == want


def _ok(body="OK"):
    # ZKTeco firmware expects a bare text body; anything else and some models
    # retry the whole batch forever.
    return HttpResponse(body, content_type="text/plain")


@csrf_exempt
def cdata(request, secret):
    """Handshake (GET) and record upload (POST).

    GET  /iclock/cdata?SN=…&options=all   -> the device asks how to behave
    POST /iclock/cdata?SN=…&table=ATTLOG  -> tab-separated punch records
    """
    if not _secret_ok(secret):
        log.warning("ADMS call with a bad secret from %s",
                    request.META.get("REMOTE_ADDR"))
        return HttpResponseForbidden("NO")
    serial = request.GET.get("SN") or request.GET.get("sn") or ""
    device = svc.device_by_serial(serial)
    if device is None:
        # An unregistered terminal is refused: a punch we cannot attribute to a
        # site is worse than no punch at all.
        log.warning("ADMS punch from unregistered serial %r (%s)", serial,
                    request.META.get("REMOTE_ADDR"))
        return _ok("OK")            # never reveal whether a serial is known
    if request.method == "GET":
        svc.touch(device)
        # Tell the device to push attendance as it happens and not to expect
        # us to hold biometric templates: they stay on the terminal.
        return _ok("GET OPTION FROM: " + serial + "\r\n"
                   "ATTLOGStamp=None\r\n"
                   "OPERLOGStamp=None\r\n"
                   "ErrorDelay=60\r\n"
                   "Delay=30\r\n"
                   "TransTimes=00:00;12:00\r\n"
                   "TransInterval=1\r\n"
                   "TransFlag=100000000000\r\n"
                   "Realtime=1\r\n"
                   "TimeZone=5\r\n"
                   "Encrypt=None\r\n")
    table = (request.GET.get("table") or "").upper()
    body = request.body.decode("utf-8", errors="replace")
    if table and table != "ATTLOG":
        # Operation logs and the like: acknowledged so the device clears them,
        # but we keep only attendance.
        svc.touch(device)
        return _ok("OK")
    tally = svc.record_punches(device, body)
    log.info("ADMS %s: %s", device.serial, tally)
    return _ok(f"OK: {tally['stored']}")


@csrf_exempt
def getrequest(request, secret):
    """The device asking for commands. Phase 1 sends none — we only listen."""
    if not _secret_ok(secret):
        return HttpResponseForbidden("NO")
    device = svc.device_by_serial(request.GET.get("SN")
                                  or request.GET.get("sn") or "")
    if device is not None:
        svc.touch(device)
    return _ok("OK")


@csrf_exempt
def devicecmd(request, secret):
    """Command results. Nothing is commanded in Phase 1; acknowledged so the
    device does not retry."""
    if not _secret_ok(secret):
        return HttpResponseForbidden("NO")
    return _ok("OK")
