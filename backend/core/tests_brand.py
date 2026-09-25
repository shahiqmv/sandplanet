"""The brand layer (MARINE_BUILD_BRIEF.md §2): Sand Planet's look is the
default, a sister instance overrides it with company parameters, and every
PDF and screen reads the same values."""
from django.core.files.uploadedfile import SimpleUploadedFile
from django.template import Context, Template

from . import brand
from .models import CompanyParameter, User
from .tests import BaseCase, make_user


class BrandTests(BaseCase):
    def setUp(self):
        super().setUp()
        brand.invalidate()

    def test_defaults_are_sand_planet_and_the_endpoint_is_public(self):
        self.client.logout()
        r = self.client.get("/api/v1/brand")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["name"], "SAND PLANET")
        self.assertEqual(r.data["colours"]["primary"], "#16527E")
        self.assertEqual(r.data["colours"]["accent"], "#29ABE2")
        self.assertTrue(r.data["features"]["trading"])
        self.assertFalse(r.data["features"]["rental"])
        self.assertEqual([a["key"] for a in r.data["apps"]], ["planet", "trading"])
        self.assertIsNone(r.data["wordmark_white_url"])

    def test_a_sister_instance_sets_its_own_brand(self):
        self.login(self.admin)
        for k, v in {"brand_name": "SANDPLANET MARINE", "brand_tagline": "Marine & Fleet",
                     "brand_short_code": "SPM", "brand_primary_deep": "#0E1C29",
                     "brand_accent_deep": "#2E6FA6", "brand_soft2": "#EAF3F9"}.items():
            r = self.client.put(f"/api/v1/parameters/{k}", {"value": v}, format="json")
            self.assertEqual(r.status_code, 200, r.data)
        self.client.put("/api/v1/parameters/features",
                        {"value": {"trading": False, "rental": True}}, format="json")
        self.client.put("/api/v1/parameters/apps",
                        {"value": [{"key": "planet-sp", "name": "Sand Planet Projects",
                                    "url": "https://app.sandplanet.mv/"}]}, format="json")
        r = self.client.get("/api/v1/brand").data
        self.assertEqual(r["name"], "SANDPLANET MARINE")
        self.assertEqual(r["short_code"], "SPM")
        self.assertEqual(r["colours"]["primary_deep"], "#0E1C29")
        self.assertEqual(r["colours"]["primary"], "#16527E")      # untouched → default
        self.assertEqual(r["features"], {"trading": False, "rental": True, "profile": True})
        self.assertEqual([a["key"] for a in r["apps"]], ["planet", "planet-sp"])   # no trading
        # the PDF templates read the same values through the tag
        t = Template('{% load brand %}{% brand "primary_deep" %}|{% brand "accent" %}')
        self.assertEqual(t.render(Context({})), "#0E1C29|#29ABE2")
        # a blank parameter falls back to the default
        self.client.put("/api/v1/parameters/brand_primary_deep", {"value": ""}, format="json")
        self.assertEqual(brand.colour("primary_deep"), "#0e3a5c")

    def test_the_templates_carry_no_literal_brand_colour(self):
        import glob
        import re
        from django.conf import settings
        pat = re.compile(r"#16527e|#29abe2|#1685cc|#10344f|#0c4e82|#26a9e0", re.I)
        offenders = [p for p in glob.glob(str(settings.BASE_DIR / "pdf_templates" / "**" / "*.html"),
                                          recursive=True) if pat.search(open(p).read())]
        self.assertEqual(offenders, [])

    def test_brand_files_are_admin_only_and_feed_the_letterhead_mark(self):
        from .pdf import mark_src
        self.assertTrue(mark_src().endswith("sp-mark.svg"))
        self.login(self.pm)
        r = self.client.post("/api/v1/company/brand/mark",
                             {"file": SimpleUploadedFile("m.png", b"\x89PNG\r\n\x1a\nxx", "image/png")})
        self.assertEqual(r.status_code, 403)
        self.login(self.admin)
        r = self.client.post("/api/v1/company/brand/mark",
                             {"file": SimpleUploadedFile("m.png", b"\x89PNG\r\n\x1a\nxx", "image/png")})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data["uploaded"])
        self.assertIn("company/mark", mark_src())
        r = self.client.post("/api/v1/company/brand/nope", {})
        self.assertEqual(r.status_code, 404)
        r = self.client.delete("/api/v1/company/brand/mark")
        self.assertFalse(r.data["uploaded"])
        self.assertTrue(mark_src().endswith("sp-mark.svg"))

    def test_the_parameter_endpoint_still_needs_admin(self):
        self.login(make_user("fin", User.Role.FINANCE))
        r = self.client.put("/api/v1/parameters/brand_name", {"value": "x"}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(CompanyParameter.objects.filter(key="brand_name").count(), 0)
