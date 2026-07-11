from datetime import date, timedelta

from django.test import TestCase
from rest_framework.test import APIClient

from .models import Site, SitePmHistory, User
from .tests import make_user


class QABase(TestCase):
    def setUp(self):
        self.site = Site.objects.create(
            code="SJR", name="Soneva Jani", status=Site.Status.ACTIVE,
            start_date=date.today() - timedelta(days=60),
        )
        self.se = make_user("se1", User.Role.SITE_ENGINEER, site=self.site)
        self.sa = make_user("sa1", User.Role.SITE_ADMIN, site=self.site)
        self.pm = make_user("pm1", User.Role.PM, site=self.site)
        SitePmHistory.objects.create(site=self.site, pm_user=self.pm,
                                     from_date=date.today())
        self.purchasing = make_user("hop1", User.Role.HO_PURCHASING)
        self.client = APIClient()
        self.client.force_authenticate(self.se)

    def act(self, ref, action, body=None, user=None):
        if user:
            self.client.force_authenticate(user)
        return self.client.post(f"/api/v1/documents/{ref}/actions/{action}",
                                body or {}, format="json")

    def make_ir(self, previous_ir_ref=None):
        self.client.force_authenticate(self.se)
        body = {
            "doc_type": "IR", "site_id": self.site.id,
            "payload": {"discipline": "Civil", "location": "Villa 12",
                        "requested_date": (date.today() + timedelta(days=2))
                        .isoformat(),
                        "requested_time": "10:00",
                        "work_description": "Blockwork second lift, east wall",
                        "work_after": "Plastering", "ref_drawings": "AR-101",
                        "enclosed": True},
        }
        if previous_ir_ref:
            body["previous_ir_ref"] = previous_ir_ref
        r = self.client.post("/api/v1/documents", body, format="json")
        assert r.status_code == 201, r.data
        return r.data

    def ir_to_issued(self):
        ir = self.make_ir()
        self.act(ir["ref"], "submit")
        self.act(ir["ref"], "approve", user=self.pm)
        r = self.act(ir["ref"], "issue", user=self.se)
        assert r.data["status"] == "ISSUED", r.data
        return ir["ref"]

    def make_mar(self):
        self.client.force_authenticate(self.se)
        r = self.client.post("/api/v1/documents", {
            "doc_type": "MAR", "site_id": self.site.id,
            "payload": {"material_description": "Porcelain tile 600x600 grade A",
                        "manufacturer": "RAK Ceramics", "origin": "UAE",
                        "enclosures": {"sample": True, "catalogue": True},
                        "confirms_spec": True},
        }, format="json")
        assert r.status_code == 201, r.data
        return r.data

    def mar_to_issued(self):
        mar = self.make_mar()
        self.act(mar["ref"], "submit")
        self.act(mar["ref"], "approve", user=self.pm)
        r = self.act(mar["ref"], "issue", user=self.se)
        assert r.data["status"] == "ISSUED", r.data
        return mar["ref"]


class IRFlowTests(QABase):
    def test_pm_gate_then_issue(self):
        ir = self.make_ir()
        self.act(ir["ref"], "submit")
        r = self.act(ir["ref"], "issue")  # cannot skip the PM gate
        self.assertEqual(r.status_code, 400)
        r = self.act(ir["ref"], "approve", user=self.se)
        self.assertEqual(r.status_code, 403)  # SE is not the PM
        self.act(ir["ref"], "approve", user=self.pm)
        r = self.act(ir["ref"], "issue", user=self.se)
        self.assertEqual(r.data["status"], "ISSUED")
        # issued revision locked
        self.client.force_authenticate(self.se)
        r = self.client.patch(f"/api/v1/documents/{ir['ref']}",
                              {"payload": {}}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_awc_part_c_closure_cycle(self):
        ref = self.ir_to_issued()
        # HO purchasing cannot record client results
        r = self.act(ref, "record-result", {"result": "APPROVED_WITH_COMMENTS"},
                     user=self.purchasing)
        self.assertEqual(r.status_code, 403)
        r = self.act(ref, "record-result",
                     {"result": "APPROVED_WITH_COMMENTS",
                      "comment": "Fix honeycombing at grid B2",
                      "reviewed_by": "J. Perera", "position": "Resident Engineer"},
                     user=self.se)
        self.assertEqual(r.data["status"], "APPROVED_WITH_COMMENTS")
        self.assertEqual(r.data["payload"]["client_result"]["reviewed_by"],
                         "J. Perera")
        # duplicate result blocked
        r = self.act(ref, "record-result", {"result": "APPROVED"}, user=self.se)
        self.assertEqual(r.status_code, 400)
        # Part C: PM closes with corrective action
        r = self.act(ref, "close", user=self.se)
        self.assertEqual(r.status_code, 403)  # PM only
        r = self.act(ref, "close", {"comment": "Honeycomb repaired with grout"},
                     user=self.pm)
        self.assertEqual(r.data["status"], "CLOSED_BY_PM")
        r = self.act(ref, "client-verify", {"verified_by": "J. Perera"},
                     user=self.se)
        self.assertEqual(r.data["status"], "CLOSED")
        self.assertEqual(r.data["payload"]["closure"]["verified_by"], "J. Perera")
        actions = [a["action"] for a in r.data["approvals"]]
        self.assertEqual(actions, ["SUBMIT", "APPROVE", "ISSUE",
                                   "RESULT_RECORDED", "CLOSE",
                                   "CLIENT_VERIFIED"])

    def test_rejected_ir_resubmitted_under_new_number(self):
        ref = self.ir_to_issued()
        self.act(ref, "record-result", {"result": "REJECTED",
                                        "comment": "Rebar cover inadequate"},
                 user=self.se)
        # cannot chain to a non-rejected IR
        good = self.ir_to_issued()
        r = self.client.post("/api/v1/documents", {
            "doc_type": "IR", "site_id": self.site.id,
            "previous_ir_ref": good,
        }, format="json")
        self.assertEqual(r.status_code, 400)
        # resubmission quotes the rejected one
        ir2 = self.make_ir(previous_ir_ref=ref)
        self.assertEqual(ir2["previous_ir_ref"], ref)
        original = self.client.get(f"/api/v1/documents/{ref}").data
        self.assertEqual(original["resubmitted_as"], ir2["ref"])
        self.assertNotEqual(ir2["ref"], ref)  # new number (spec §4.2)


class MARFlowTests(QABase):
    def test_rr_revision_same_number_fresh_result(self):
        ref = self.mar_to_issued()
        r = self.act(ref, "record-result",
                     {"result": "REVISE_RESUBMIT",
                      "comment": "Submit water absorption test report",
                      "reviewed_by": "K. Silva"}, user=self.se)
        self.assertEqual(r.data["status"], "REVISE_RESUBMIT")
        # revise: same number, R1, back to draft, result cleared
        r = self.client.post(f"/api/v1/documents/{ref}/revisions")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["ref"], ref)
        self.assertEqual(r.data["rev_label"], "R1")
        self.assertEqual(r.data["status"], "DRAFT")
        self.assertNotIn("client_result", r.data["payload"])
        # round 2 approves with a recorded approval date
        self.act(ref, "submit")
        self.act(ref, "approve", user=self.pm)
        self.act(ref, "issue", user=self.se)
        r = self.act(ref, "record-result", {"result": "APPROVED",
                                            "reviewed_by": "K. Silva"},
                     user=self.se)
        self.assertEqual(r.data["status"], "APPROVED")
        self.assertEqual(r.data["payload"]["client_result"]["approval_date"],
                         date.today().isoformat())

    def test_invalid_result_rejected(self):
        ref = self.mar_to_issued()
        r = self.act(ref, "record-result", {"result": "MAYBE"}, user=self.se)
        self.assertEqual(r.status_code, 400)


class TWSFlowTests(QABase):
    def make_tws(self, doc_date=None):
        self.client.force_authenticate(self.se)
        return self.client.post("/api/v1/documents", {
            "doc_type": "TWS", "site_id": self.site.id,
            "doc_date": (doc_date or date.today() + timedelta(days=1))
            .isoformat(),
            "payload": {"activities": [{"activity": "Screed pool deck",
                                        "location": "Pool", "trade": "Civil"}],
                        "access_support": "Buggy for material movement"},
        }, format="json")

    def test_issue_and_acknowledge(self):
        tws = self.make_tws().data
        r = self.act(tws["ref"], "issue")
        self.assertEqual(r.data["status"], "ISSUED")
        r = self.act(tws["ref"], "acknowledge",
                     {"acknowledged_by": "Resort duty manager"}, user=self.sa)
        self.assertEqual(r.data["status"], "ACKNOWLEDGED")
        self.assertEqual(r.data["payload"]["acknowledgement"]["acknowledged_by"],
                         "Resort duty manager")

    def test_one_tws_per_day(self):
        self.make_tws()
        r = self.make_tws()
        self.assertEqual(r.status_code, 400)
        self.assertIn("already exists", r.data["detail"])
