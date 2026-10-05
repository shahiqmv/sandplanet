"""Handing a project over unit by unit (owner 2026-10-05): offered,
inspected with the client, handed over on a certificate — with minor snags
open if need be — and the unit's own defects period running from that day."""
from datetime import date
from decimal import Decimal as D

from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from .models import ProgressClaim, ProjectUnit, SnagItem, UnitHandover, User
from .tests import make_user
from .tests_units import UnitBoardBase


class UnitHandoverTests(UnitBoardBase):
    def setUp(self):
        super().setUp()
        self.project.defects_liability_months = 12
        self.project.save()
        self._generate()
        self.unit = ProjectUnit.objects.filter(project=self.project).first()
        self.today = timezone.localdate()
        self.url = f"/api/v1/units/{self.unit.id}/handover"

    def do(self, action, user=None, fmt="json", **body):
        self.client.force_authenticate(user or self.se)
        return self.client.post(f"{self.url}/{action}", body, format=fmt)

    def snag(self, **kw):
        self.client.force_authenticate(self.se)
        body = {"description": "Paint touch-up at the door frame"}
        body.update(kw)
        r = self.client.post(f"{self.url}/snags", body, format="multipart")
        assert r.status_code == 200, r.data
        return SnagItem.objects.order_by("-id").first()

    def inspected(self):
        assert self.do("offer").status_code == 200
        r = self.do("inspect", inspected_on=str(self.today),
                    client_attendees="Mr Ali, Resort Engineer")
        assert r.status_code == 200, r.data
        return r

    def test_the_steps_in_order(self):
        r = self.client.get(self.url)
        self.assertEqual(r.data["status"], "NONE")
        # nothing can be skipped
        self.assertEqual(self.do("inspect", inspected_on=str(self.today),
                                 client_attendees="x").status_code, 400)
        r = self.do("offer", proposed_inspection=str(self.today))
        self.assertEqual((r.status_code, r.data["status"]), (200, "OFFERED"))
        self.assertEqual(self.do("offer").status_code, 400)       # once
        self.assertEqual(self.do("hand-over", handed_over_on=str(self.today),
                                 client_signatory="Mr Ali").status_code, 400)
        # the inspection needs its date and who came for the client
        self.assertEqual(self.do("inspect", inspected_on=str(self.today))
                         .status_code, 400)
        r = self.do("inspect", inspected_on=str(self.today),
                    client_attendees="Mr Ali, Resort Engineer")
        self.assertEqual(r.data["status"], "INSPECTED")
        self.assertEqual(r.data["certificate_no"], "UHC-19 VILLAS-001")
        self.assertEqual(self.do("hand-over", handed_over_on=str(self.today))
                         .status_code, 400)                       # who signed
        r = self.do("hand-over", handed_over_on=str(self.today),
                    client_signatory="Mr Ali", client_position="Engineer")
        self.assertEqual((r.status_code, r.data["status"]),
                         (200, "HANDED_OVER"))

    def test_the_defects_period_runs_from_the_units_own_handover(self):
        self.inspected()
        import calendar
        day = self.today
        r = self.do("hand-over", handed_over_on=str(day),
                    client_signatory="Mr Ali")
        h = UnitHandover.objects.get(unit=self.unit)
        last = calendar.monthrange(day.year + 1, day.month)[1]
        self.assertEqual(h.defects_liability_ends(),
                         date(day.year + 1, day.month, min(day.day, last)))
        self.assertEqual(str(r.data["dlp_ends"])[:4], str(day.year + 1))
        # the project's own taking-over is untouched
        self.assertIsNone(self.project.handover.taking_over_on
                          if hasattr(self.project, "handover") else None)
        # a snag raised on the unit now is a defects-period snag
        self.assertTrue(self.snag(description="Tap leaking").in_dlp)

    def test_minor_snags_ride_with_the_handover_and_a_major_one_holds_it(self):
        self.inspected()
        minor = self.snag()
        major = self.snag(description="Pool not holding water",
                          severity="MAJOR")
        self.assertEqual((minor.unit, minor.severity, minor.location),
                         (self.unit, "MINOR", self.unit.ref))
        self.assertFalse(minor.in_dlp)
        r = self.do("hand-over", handed_over_on=str(self.today),
                    client_signatory="Mr Ali")
        self.assertEqual(r.status_code, 400)
        self.assertIn(major.ref_no, r.data["detail"])
        # the PM closes the major one; the minor one stays open
        self.client.force_authenticate(self.pm)
        self.client.patch(f"/api/v1/handover/snags/{major.id}",
                          {"status": "CLOSED"}, format="json")
        r = self.do("hand-over", handed_over_on=str(self.today),
                    client_signatory="Mr Ali")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual((r.data["snags_open"], r.data["snags_total"]),
                         (1, 2))

    def test_the_board_and_the_certificate(self):
        self.inspected()
        self.snag()
        self.client.force_authenticate(self.pm)
        board = self.client.get(
            f"/api/v1/projects/{self.project.id}/units").data
        row = next(u for u in board["units"] if u["id"] == self.unit.id)
        self.assertEqual((row["handover"]["status"],
                          row["handover"]["snags_open"]), ("INSPECTED", 1))
        self.assertEqual(board["handed_over"], 0)
        r = self.client.get(f"{self.url}/certificate.pdf")
        self.assertEqual(r.status_code, 200)
        import pymupdf
        doc = pymupdf.open("pdf", r.content)
        text = "".join(p.get_text() for p in doc)
        doc.close()
        self.assertIn("UNIT HANDOVER CERTIFICATE", text)
        self.assertIn("Paint touch-up", text)
        self.assertIn("12 months", text)
        f = SimpleUploadedFile("signed.pdf", b"%PDF-1.4 x",
                               content_type="application/pdf")
        r = self.do("hand-over", fmt="multipart",
                    handed_over_on=str(self.today), client_signatory="Mr Ali",
                    signed_copy=f)
        self.assertTrue(r.data["signed_copy_url"])
        self.client.force_authenticate(self.pm)
        board = self.client.get(
            f"/api/v1/projects/{self.project.id}/units").data
        self.assertEqual(board["handed_over"], 1)

    def test_a_step_is_taken_back_by_the_pm_with_a_reason(self):
        self.inspected()
        self.snag()
        self.do("hand-over", handed_over_on=str(self.today),
                client_signatory="Mr Ali")
        self.assertEqual(self.do("step-back", reason="wrong villa")
                         .status_code, 403)                # site engineer
        self.assertEqual(self.do("step-back", user=self.pm).status_code, 400)
        r = self.do("step-back", user=self.pm, reason="wrong villa")
        self.assertEqual(r.data["status"], "INSPECTED")
        self.do("step-back", user=self.pm, reason="wrong villa")
        r = self.do("step-back", user=self.pm, reason="wrong villa")
        self.assertEqual(r.data["status"], "NONE")
        self.assertEqual(SnagItem.objects.filter(unit=self.unit).count(), 1)

    def test_other_sites_and_claims_are_untouched(self):
        from .models import Site
        other = Site.objects.create(code="ZZZ", name="Elsewhere",
                                    status=Site.Status.ACTIVE)
        stranger = make_user("uh_x", User.Role.SITE_ENGINEER, site=other)
        self.client.force_authenticate(stranger)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.inspected()
        self.do("hand-over", handed_over_on=str(self.today),
                client_signatory="Mr Ali")
        self.assertEqual(ProgressClaim.objects.count(), 0)
        self.project.refresh_from_db()
        self.assertEqual(D(str(self.project.contract_value)), D("500000"))
