"""A PDF is rendered once per version of its content.

The 38-page IPA-02 takes WeasyPrint ~40 s on the production box, and the
template is not the lever (measured 2026-09-03). So the second open of an
unchanged application must not touch the engine at all.
"""
from unittest import mock

from django.core.files.storage import default_storage
from django.test import TestCase, override_settings

from . import pdf_cache


@override_settings(MEDIA_ROOT="test-media")
class PdfCacheTests(TestCase):
    def setUp(self):
        for name in default_storage.listdir(pdf_cache.PREFIX)[1] \
                if default_storage.exists(pdf_cache.PREFIX) else []:
            default_storage.delete(pdf_cache.PREFIX + name)

    def _fake_engine(self):
        m = mock.MagicMock()
        m.return_value.write_pdf.return_value = b"%PDF-1.4 fake"
        return m

    def test_the_second_render_of_the_same_html_skips_the_engine(self):
        html = "<html><body><p>IPA-02</p></body></html>"
        with mock.patch("weasyprint.HTML", self._fake_engine()) as eng:
            first = pdf_cache.cached_pdf(html)
            second = pdf_cache.cached_pdf(html)
        self.assertEqual(first, b"%PDF-1.4 fake")
        self.assertEqual(second, b"%PDF-1.4 fake")
        self.assertEqual(eng.call_count, 1)

    def test_any_change_to_the_content_is_a_new_document(self):
        with mock.patch("weasyprint.HTML", self._fake_engine()) as eng:
            pdf_cache.cached_pdf("<p>88.00%</p>")
            pdf_cache.cached_pdf("<p>88.01%</p>")
        self.assertEqual(eng.call_count, 2)

    def test_warming_stores_without_returning(self):
        html = "<p>warm</p>"
        with mock.patch("weasyprint.HTML", self._fake_engine()) as eng:
            self.assertIsNone(pdf_cache.cached_pdf(html, warm_only=True))
            got = pdf_cache.cached_pdf(html)
        self.assertEqual(got, b"%PDF-1.4 fake")
        self.assertEqual(eng.call_count, 1)

    def test_the_engine_and_font_subsetter_do_not_log_at_info(self):
        from django.conf import settings
        loggers = settings.LOGGING["loggers"]
        self.assertEqual(loggers["weasyprint"]["level"], "WARNING")
        self.assertEqual(loggers["fontTools"]["level"], "WARNING")
