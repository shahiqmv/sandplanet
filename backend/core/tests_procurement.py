from datetime import date, timedelta

from django.test import TestCase
from rest_framework.test import APIClient

from .models import Document, Item, PendingItem, Site, SitePmHistory, User
from .tests import make_user


class ProcBase(TestCase):
    def setUp(self):
        self.site = Site.objects.create(
            code="SJR", name="Soneva Jani", status=Site.Status.ACTIVE,
            start_date=date.today() - timedelta(days=60),
        )
        self.other_site = Site.objects.create(code="VKR", name="Vakkaru",
                                              status=Site.Status.ACTIVE)
        self.sa = make_user("sa1", User.Role.SITE_ADMIN, site=self.site)
        self.se = make_user("se1", User.Role.SITE_ENGINEER, site=self.site)
        self.pm = make_user("pm1", User.Role.PM, site=self.site)
        SitePmHistory.objects.create(site=self.site, pm_user=self.pm,
                                     from_date=date.today())
        self.purchasing = make_user("hop1", User.Role.HO_PURCHASING)
        self.director = make_user("dir1", User.Role.DIRECTOR)
        self.signatory = make_user("sig1", User.Role.SIGNATORY)
        self.finance = make_user("fin1", User.Role.FINANCE)
        # 9xxxx codes keep clear of the server-issued counter range
        self.cement = Item.objects.create(code="ITM-90001",
                                          description="Cement OPC 50kg bag",
                                          unit="bag", category="Civil")
        self.rebar = Item.objects.create(code="ITM-90002",
                                         description="Rebar B500 12mm",
                                         unit="kg", category="Civil")
        self.client = APIClient()

    def as_user(self, user):
        self.client.force_authenticate(user)

    def act(self, ref, action, body=None):
        return self.client.post(f"/api/v1/documents/{ref}/actions/{action}",
                                body or {}, format="json")

    def make_mr(self, lines=None):
        self.as_user(self.sa)
        r = self.client.post("/api/v1/documents", {
            "doc_type": "MR", "site_id": self.site.id,
            "payload": {"planned_loading": "August hired boat",
                        "trades_covered": "Civil - Villa 12",
                        "required_by": "2026-08-01", "stock_attested": True},
            "lines": lines or [
                {"item_id": self.cement.id, "qty_required": 200, "qty_stock": 50,
                 "qty_to_order": 150, "priority": "NORMAL", "remarks": "Civil"},
                {"item_id": self.rebar.id, "qty_required": 500, "qty_stock": 0,
                 "qty_to_order": 500, "priority": "NORMAL", "remarks": "Civil"},
            ],
        }, format="json")
        assert r.status_code == 201, r.data
        return r.data

    def mr_to_sent(self):
        mr = self.make_mr()
        self.act(mr["ref"], "submit")
        self.as_user(self.pm)
        self.act(mr["ref"], "approve")
        self.as_user(self.sa)
        r = self.act(mr["ref"], "send")
        assert r.data["status"] == "SENT_TO_HO", r.data
        return mr["ref"]


    def make_pr(self, mr_ref):
        self.as_user(self.purchasing)
        r = self.client.post("/api/v1/documents", {
            "doc_type": "PR", "site_id": self.site.id,
            "mr_refs": [mr_ref],
            "payload": {"requested_delivery": "2026-07-25"},
            "lines": [{"free_text_desc": "Male' Hardware Pvt Ltd",
                       "vendor": "Male' Hardware Pvt Ltd",
                       "quotation_ref": "QT-4411", "payment_terms": "COD",
                       "amount_cash": 84000, "amount_credit": 0}],
        }, format="json")
        assert r.status_code == 201, r.data
        return r.data

    def make_lm(self, mr_ref, pr_ref=None, lines=None):
        self.as_user(self.purchasing)
        body = {
            "doc_type": "LM", "site_id": self.site.id,
            "mr_refs": [mr_ref],
            "payload": {"vessel": "MV Dhoni 7", "departure_point": "Male'",
                        "expected_arrival": "2026-07-20"},
            "lines": lines or [
                {"item_id": self.cement.id, "qty_loaded": 150, "qty_pending": 0},
                {"item_id": self.rebar.id, "qty_loaded": 300, "qty_pending": 200},
            ],
        }
        if pr_ref:
            body["pr_refs"] = [pr_ref]
        r = self.client.post("/api/v1/documents", body, format="json")
        assert r.status_code == 201, r.data
        return r.data


class ItemMasterTests(ProcBase):
    def test_purchasing_creates_item_with_server_code(self):
        self.as_user(self.purchasing)
        r = self.client.post("/api/v1/items", {"description": "PVC pipe 63mm",
                                               "unit": "m", "category": "MEP"},
                             format="json")
        self.assertEqual(r.status_code, 201)
        self.assertTrue(r.data["code"].startswith("ITM-"))

    def test_site_roles_add_item_but_cannot_edit(self):
        # Site staff may add a MISSING item (approval gate off for now)
        self.as_user(self.sa)
        r = self.client.post("/api/v1/items",
                             {"description": "Site Added Bolt M10", "unit": "no"},
                             format="json")
        self.assertEqual(r.status_code, 201, r.data)
        # but they cannot edit an existing catalogue item
        existing = Item.objects.first()
        r = self.client.patch(f"/api/v1/items/{existing.id}",
                              {"description": "hacked"}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_search_and_merge(self):
        self.as_user(self.purchasing)
        r = self.client.get("/api/v1/items?search=cement")
        self.assertEqual(len(r.data), 1)
        dup = Item.objects.create(code="ITM-00099",
                                  description="Cement OPC 50 kg (dup)", unit="bag")
        r = self.client.post(f"/api/v1/items/{dup.id}/merge",
                             {"target_id": self.cement.id}, format="json")
        self.assertEqual(r.status_code, 200)
        dup.refresh_from_db()
        self.assertEqual(dup.merged_into_id, self.cement.id)
        r = self.client.get("/api/v1/items?search=dup")
        self.assertEqual(len(r.data), 0)  # merged items leave the catalog


class MRFlowTests(ProcBase):
    def test_site_engineer_has_site_admin_parity(self):
        """Site Engineer can raise + send an MR and confirm a GRN count —
        full site-task parity with Site Admin (owner, 2026-07-13)."""
        self.as_user(self.se)      # SITE_ENGINEER
        r = self.client.post("/api/v1/documents", {
            "doc_type": "MR", "site_id": self.site.id,
            "payload": {"stock_attested": True},
            "lines": [{"item_id": self.cement.id, "qty_required": 10,
                       "qty_stock": 0, "qty_to_order": 10}],
        }, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        ref = r.data["ref"]
        # submit (engineer) → PM approves → engineer sends to HO
        self.assertEqual(self.act(ref, "submit").data["status"], "SUBMITTED")
        self.as_user(self.pm)
        self.act(ref, "approve")
        self.as_user(self.se)
        self.assertEqual(self.act(ref, "send").data["status"], "SENT_TO_HO")

    def test_urgent_line_requires_reason(self):
        self.as_user(self.sa)
        r = self.client.post("/api/v1/documents", {
            "doc_type": "MR", "site_id": self.site.id,
            "lines": [{"item_id": self.cement.id, "qty_required": 10,
                       "priority": "URGENT"}],
        }, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("urgent", r.data["detail"].lower())

    def test_unit_locked_from_catalog(self):
        mr = self.make_mr()
        self.assertEqual(mr["lines"][0]["unit"], "bag")
        self.assertEqual(mr["lines"][0]["item_code"], "ITM-90001")
        self.assertFalse(mr["lines"][0]["is_free_text"])

    def test_free_text_line_flagged(self):
        mr = self.make_mr(lines=[{"free_text_desc": "Specialty epoxy grout",
                                  "unit": "kg", "qty_required": 5}])
        self.assertTrue(mr["lines"][0]["is_free_text"])

    def test_pm_gate_and_send(self):
        mr = self.make_mr()
        r = self.act(mr["ref"], "send")
        self.assertEqual(r.status_code, 400)  # cannot send from DRAFT
        self.act(mr["ref"], "submit")
        self.as_user(self.se)
        r = self.act(mr["ref"], "approve")
        self.assertEqual(r.status_code, 403)  # engineer is not the PM
        self.as_user(self.pm)
        r = self.act(mr["ref"], "approve")
        self.assertEqual(r.data["status"], "PM_APPROVED")
        self.as_user(self.sa)
        r = self.act(mr["ref"], "send")
        self.assertEqual(r.data["status"], "SENT_TO_HO")
        # sent revision is locked
        r = self.client.patch(f"/api/v1/documents/{mr['ref']}",
                              {"payload": {}}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_return_with_comment_goes_back_to_draft(self):
        mr = self.make_mr()
        self.act(mr["ref"], "submit")
        self.as_user(self.pm)
        r = self.act(mr["ref"], "return")
        self.assertEqual(r.status_code, 400)  # comment required
        r = self.act(mr["ref"], "return", {"comment": "Split by trade please"})
        self.assertEqual(r.data["status"], "DRAFT")

    def test_amendment_revision_flags_changed_lines(self):
        ref = self.mr_to_sent()
        r = self.client.post(f"/api/v1/documents/{ref}/revisions")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["rev_label"], "R1")
        self.assertEqual(r.data["status"], "DRAFT")
        # change cement qty, keep rebar, add a new item line
        r = self.client.patch(f"/api/v1/documents/{ref}", {"lines": [
            {"item_id": self.cement.id, "qty_required": 300, "qty_stock": 50,
             "qty_to_order": 250, "priority": "NORMAL", "remarks": "Civil"},
            {"item_id": self.rebar.id, "qty_required": 500, "qty_stock": 0,
             "qty_to_order": 500, "priority": "NORMAL", "remarks": "Civil"},
            {"free_text_desc": "Waterproofing membrane", "unit": "roll",
             "qty_required": 12},
        ]}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        flags = {(line["item_code"] or line["free_text_desc"]): line["is_changed"]
                 for line in r.data["lines"]}
        self.assertTrue(flags["ITM-90001"])              # qty changed
        self.assertFalse(flags["ITM-90002"])             # untouched
        self.assertTrue(flags["Waterproofing membrane"])  # new line
        # both revisions remain visible
        self.assertEqual([rev["rev_label"] for rev in r.data["revisions"]],
                         ["R0", "R1"])

    def test_register_shows_one_row_per_mr_current_revision(self):
        ref = self.mr_to_sent()
        self.client.post(f"/api/v1/documents/{ref}/revisions")  # revise -> R1
        self.as_user(self.purchasing)
        r = self.client.get("/api/v1/registers/mr")
        rows = [row for row in r.data["rows"] if row["ref"] == ref]
        self.assertEqual(len(rows), 1)         # one row per MR, not per revision
        self.assertEqual(rows[0]["rev"], "R1")  # showing the current revision


class ChainTests(ProcBase):

    def test_pr_numbering_is_global(self):
        mr_ref = self.mr_to_sent()
        pr = self.make_pr(mr_ref)
        self.assertEqual(pr["ref"], "PR-001")  # no site code (spec §4.1)

    def test_site_roles_cannot_create_pr(self):
        mr_ref = self.mr_to_sent()
        self.as_user(self.sa)
        r = self.client.post("/api/v1/documents", {
            "doc_type": "PR", "site_id": self.site.id, "mr_refs": [mr_ref],
        }, format="json")
        self.assertEqual(r.status_code, 403)

    def test_pr_approval_marks_mr_pr_raised(self):
        mr_ref = self.mr_to_sent()
        pr = self.make_pr(mr_ref)
        self.act(pr["ref"], "submit")
        self.as_user(self.purchasing)
        r = self.act(pr["ref"], "approve")
        self.assertEqual(r.status_code, 403)  # only the Director approves
        self.as_user(self.director)
        r = self.act(pr["ref"], "approve")
        self.assertEqual(r.data["status"], "APPROVED")
        self.assertEqual(Document.objects.get(ref=mr_ref).status, "PR_RAISED")

    def test_vendor_payment_recording(self):
        """R3 addendum: payments recorded per vendor row; status advances
        as vendors settle; slip file attaches to the PR."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import override_settings

        mr_ref = self.mr_to_sent()
        self.as_user(self.purchasing)
        pr = self.client.post("/api/v1/documents", {
            "doc_type": "PR", "site_id": self.site.id, "mr_refs": [mr_ref],
            "lines": [
                {"free_text_desc": "Vendor A", "vendor": "Vendor A",
                 "amount_cash": 5000},
                {"free_text_desc": "Vendor B", "vendor": "Vendor B",
                 "amount_credit": 7000},
            ],
        }, format="json").data
        self.act(pr["ref"], "submit")
        line_a = pr["lines"][0]["id"]
        line_b = pr["lines"][1]["id"]
        # blocked before authorisation (Finance, so it is the status gate)
        self.as_user(self.finance)
        r = self.client.post(f"/api/v1/pr/{pr['ref']}/vendor-payment",
                             {"line_id": line_a, "payment_ref": "TRF-1"})
        self.assertEqual(r.status_code, 400)
        self.as_user(self.director)
        self.act(pr["ref"], "approve")
        # still blocked after Director approval — needs signatory (§6C.2)
        self.as_user(self.finance)
        r = self.client.post(f"/api/v1/pr/{pr['ref']}/vendor-payment",
                             {"line_id": line_a, "payment_ref": "TRF-1"})
        self.assertEqual(r.status_code, 400)
        # authorisation runs on a payment voucher (M6d)
        self.as_user(self.finance)
        pv = self.client.post("/api/v1/payment-vouchers",
                              {"source_refs": [pr["ref"]]},
                              format="json").data["ref"]
        self.client.post(f"/api/v1/payment-vouchers/{pv}/actions/submit", {},
                         format="json")
        self.as_user(self.signatory)
        r = self.client.post(
            f"/api/v1/payment-vouchers/{pv}/actions/approve", {},
            format="json")
        self.assertEqual(r.status_code, 200, r.data)
        # site roles cannot record payments
        self.as_user(self.sa)
        r = self.client.post(f"/api/v1/pr/{pr['ref']}/vendor-payment",
                             {"line_id": line_a, "payment_ref": "TRF-1"})
        self.assertEqual(r.status_code, 403)
        # purchasing can no longer record payments — that is Finance's role
        self.as_user(self.purchasing)
        r = self.client.post(f"/api/v1/pr/{pr['ref']}/vendor-payment",
                             {"line_id": line_a, "payment_ref": "X"})
        self.assertEqual(r.status_code, 403)
        # Finance settles vendor A with the slip attached
        self.as_user(self.finance)
        with override_settings(MEDIA_ROOT="test-media"):
            slip = SimpleUploadedFile("slip.pdf", b"%PDF-1.4 slip",
                                      content_type="application/pdf")
            r = self.client.post(f"/api/v1/pr/{pr['ref']}/vendor-payment",
                                 {"line_id": line_a, "payment_ref": "TRF-1",
                                  "file": slip}, format="multipart")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "PAYMENT_PROCESSING")  # partial
        self.assertIsNotNone(r.data["slip_url"])
        self.assertTrue(any(a["kind"] == "PAYMENT_SLIP" and
                            a["caption"] == "Vendor A"
                            for a in r.data["attachments"]))
        # finance settles vendor B -> fully paid
        self.as_user(self.finance)
        r = self.client.post(f"/api/v1/pr/{pr['ref']}/vendor-payment",
                             {"line_id": line_b, "payment_ref": "VCH-9"})
        self.assertEqual(r.data["status"], "PAID_PO_ISSUED")
        refs = {ln["vendor"]: ln["action_taken"] for ln in r.data["lines"]}
        self.assertEqual(refs, {"Vendor A": "TRF-1", "Vendor B": "VCH-9"})


    def test_lm_departure_creates_pending_and_updates_mr(self):
        mr_ref = self.mr_to_sent()
        lm = self.make_lm(mr_ref)
        r = self.act(lm["ref"], "depart")
        self.assertEqual(r.data["status"], "DEPARTED")
        self.assertEqual(Document.objects.get(ref=mr_ref).status,
                         "PARTIALLY_LOADED")
        pending = PendingItem.objects.filter(site=self.site, status="PENDING")
        self.assertEqual(pending.count(), 1)
        self.assertEqual(pending[0].item_id, self.rebar.id)
        self.assertEqual(float(pending[0].qty_pending), 200.0)

    def test_second_lm_clears_pending(self):
        mr_ref = self.mr_to_sent()
        lm1 = self.make_lm(mr_ref)
        self.act(lm1["ref"], "depart")
        lm2 = self.make_lm(mr_ref, lines=[
            {"item_id": self.rebar.id, "qty_loaded": 200, "qty_pending": 0},
        ])
        self.act(lm2["ref"], "depart")
        row = PendingItem.objects.get(item=self.rebar,
                                      lm_line__revision__document__ref=lm1["ref"])
        self.assertEqual(row.status, "CLEARED")
        self.assertEqual(row.cleared_lm.ref, lm2["ref"])
        self.assertEqual(Document.objects.get(ref=mr_ref).status, "LOADED")

    def test_grn_prefill_count_verify_shortage(self):
        mr_ref = self.mr_to_sent()
        lm = self.make_lm(mr_ref)
        self.act(lm["ref"], "depart")
        # Site admin raises the GRN from the manifest
        self.as_user(self.sa)
        r = self.client.post("/api/v1/documents", {
            "doc_type": "GRN", "site_id": self.site.id, "lm_ref": lm["ref"],
        }, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        grn = r.data
        self.assertEqual(grn["payload"]["manifest_ref"], lm["ref"])
        self.assertEqual(grn["payload"]["vessel"], "MV Dhoni 7")
        manifest_qty = {line["item_code"]: line["qty_manifest"]
                        for line in grn["lines"]}
        self.assertEqual(float(manifest_qty["ITM-90001"]), 150.0)
        # count received: cement short by 10
        r = self.client.patch(f"/api/v1/documents/{grn['ref']}", {"lines": [
            {"item_id": self.cement.id, "qty_manifest": 150, "qty_received": 140,
             "remarks": "10 bags torn"},
            {"item_id": self.rebar.id, "qty_manifest": 300, "qty_received": 300},
        ]}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        r = self.act(grn["ref"], "count")
        self.assertEqual(r.data["status"], "COUNTED")
        self.as_user(self.se)
        r = self.act(grn["ref"], "verify")
        self.assertEqual(r.data["status"], "SHORTAGE_REPORTED")
        self.assertEqual(Document.objects.get(ref=lm["ref"]).status,
                         "RECEIVED_WITH_SHORTAGE")
        # verified GRN is immutable
        r = self.client.patch(f"/api/v1/documents/{grn['ref']}",
                              {"payload": {}}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_grn_full_receipt_completes(self):
        mr_ref = self.mr_to_sent()
        lm = self.make_lm(mr_ref, lines=[
            {"item_id": self.cement.id, "qty_loaded": 150, "qty_pending": 0},
        ])
        self.act(lm["ref"], "depart")
        self.as_user(self.sa)
        grn = self.client.post("/api/v1/documents", {
            "doc_type": "GRN", "site_id": self.site.id, "lm_ref": lm["ref"],
        }, format="json").data
        self.client.patch(f"/api/v1/documents/{grn['ref']}", {"lines": [
            {"item_id": self.cement.id, "qty_manifest": 150, "qty_received": 150},
        ]}, format="json")
        self.act(grn["ref"], "count")
        self.as_user(self.pm)
        r = self.act(grn["ref"], "verify")
        self.assertEqual(r.data["status"], "COMPLETE")
        self.assertEqual(Document.objects.get(ref=lm["ref"]).status, "RECEIVED")


class HOEndpointTests(ProcBase):
    def test_pending_items_scoped_to_site_user(self):
        mr_ref = self.mr_to_sent()
        lm = self.make_lm(mr_ref)
        self.act(lm["ref"], "depart")
        self.as_user(self.sa)
        r = self.client.get("/api/v1/pending-items")
        self.assertEqual(len(r.data), 1)
        outsider = make_user("sa2", User.Role.SITE_ADMIN, site=self.other_site)
        self.as_user(outsider)
        r = self.client.get("/api/v1/pending-items")
        self.assertEqual(len(r.data), 0)

    def test_pending_manual_clear_requires_reason(self):
        mr_ref = self.mr_to_sent()
        lm = self.make_lm(mr_ref)
        self.act(lm["ref"], "depart")
        row_id = PendingItem.objects.get(status="PENDING").id
        self.as_user(self.purchasing)
        r = self.client.patch(f"/api/v1/pending-items/{row_id}",
                              {"clear": True}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.client.patch(f"/api/v1/pending-items/{row_id}",
                              {"clear": True, "cleared_reason": "Cancelled by site"},
                              format="json")
        self.assertEqual(r.data["status"], "CLEARED")

    def test_ho_dashboard_counts(self):
        mr_ref = self.mr_to_sent()
        pr = self.make_pr(mr_ref)
        self.act(pr["ref"], "submit")
        self.as_user(self.director)
        r = self.client.get("/api/v1/dashboards/ho")
        self.assertEqual(r.data["mrs_awaiting_action"], 1)
        self.assertEqual(r.data["prs_awaiting_approval"], 1)
        self.as_user(self.sa)
        r = self.client.get("/api/v1/dashboards/ho")
        self.assertEqual(r.status_code, 403)
