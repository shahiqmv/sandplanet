"""No framework developer surface is reachable — and it stays that way.

The same checks entrypoint.sh runs at deploy, run here so CI fails first
(owner 2026-09-02, after a PM was shown the browsable API)."""
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from . import checks

BROWSER = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"


class HardeningChecksTests(TestCase):
    def test_every_production_check_passes(self):
        for fn in (checks.api_renders_json_only, checks.no_admin_site,
                   checks.no_developer_apps, checks.debug_is_off):
            self.assertEqual(fn(None), [], fn.__name__)

    def test_debug_on_is_an_error_not_a_warning(self):
        with override_settings(DEBUG=True):
            self.assertEqual([e.id for e in checks.debug_is_off(None)],
                             ["core.E005"])

    def test_an_html_renderer_anywhere_is_caught(self):
        with override_settings(REST_FRAMEWORK={
                "DEFAULT_RENDERER_CLASSES": [
                    "rest_framework.renderers.JSONRenderer",
                    "rest_framework.renderers.BrowsableAPIRenderer"]}):
            ids = [e.id for e in checks.api_renders_json_only(None)]
        self.assertIn("core.E001", ids)

    def test_a_developer_app_is_caught(self):
        """Patched at the check, not installed — the package is not present
        here, which is the point."""
        from types import SimpleNamespace
        from unittest import mock
        fake = SimpleNamespace(INSTALLED_APPS=["core", "debug_toolbar"])
        with mock.patch.object(checks, "settings", fake):
            self.assertEqual([e.id for e in checks.no_developer_apps(None)],
                             ["core.E004"])


class HardeningHttpTests(TestCase):
    """What a person's browser actually gets."""

    def setUp(self):
        self.client = APIClient()

    def test_a_browser_on_an_api_url_gets_json_never_a_page(self):
        for url in ("/api/v1/payroll/runs", "/api/v1/payroll/lines/1",
                    "/api/v1/attendance/register", "/api/v1/"):
            r = self.client.get(url, HTTP_ACCEPT=BROWSER)
            self.assertEqual(r["Content-Type"].split(";")[0],
                             "application/json", url)
            self.assertNotIn(b"<html", r.content.lower(), url)

    def test_the_django_admin_does_not_exist(self):
        for url in ("/admin/", "/admin/login/", "/admin/core/user/"):
            self.assertEqual(self.client.get(url).status_code, 404, url)

    def test_an_unknown_url_is_a_plain_404(self):
        r = self.client.get("/api/v1/no-such-thing", HTTP_ACCEPT=BROWSER)
        self.assertEqual(r.status_code, 404)
        self.assertNotIn(b"URLconf", r.content)     # the DEBUG 404 page
