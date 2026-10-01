"""Tools & Equipment register: GRN routing, faulty/repair cycle, DPR summary."""
from datetime import date, timedelta

from django.test import TestCase
from rest_framework.test import APIClient

from . import procurement, tools
from .models import (Document, DocumentLine, DocumentRevision, Item,
                     ItemCategory, Site, StockMovement, ToolAsset, User)
from .tests import make_user


class ToolsBase(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="SJR", name="Soneva Jani",
                                        status=Site.Status.ACTIVE,
                                        start_date=date.today() - timedelta(days=5))
        self.sa = make_user("sa", User.Role.SITE_ADMIN, site=self.site)
        ItemCategory.objects.update_or_create(
            name="Tools & Equipment", defaults={"is_tool": True})
        ItemCategory.objects.update_or_create(
            name="Civil", defaults={"is_tool": False})
        self.drill = Item.objects.create(code="ITM-90005",
                                         description="Battery drill", unit="nos",
                                         category="Tools & Equipment",
                                         brand="Makita")
        self.cement = Item.objects.create(code="ITM-90001",
                                          description="Cement", unit="bag",
                                          category="Civil")
        self.client = APIClient()
        self.client.force_authenticate(self.sa)

    def verified_grn(self, lines):
        """Build a COUNTED GRN with the given (item, qty) lines and verify it."""
        grn = Document.objects.create(
            doc_type="GRN", site=self.site, doc_date=date.today(),
            status="COUNTED", ref="GRN-SJR-001", created_by=self.sa)
        rev = DocumentRevision.objects.create(document=grn, rev_label="R0",
                                              payload={}, created_by=self.sa)
        grn.current_revision = rev
        grn.save(update_fields=["current_revision"])
        for i, (item, qty) in enumerate(lines, 1):
            DocumentLine.objects.create(revision=rev, line_no=i, item=item,
                                        qty_manifest=qty, qty_received=qty)
        procurement.on_grn_verified(grn, self.sa)
        return grn


class ToolsRoutingTests(ToolsBase):
    def test_grn_tool_lines_go_to_register_not_stock(self):
        self.verified_grn([(self.drill, 3), (self.cement, 100)])
        # 3 drill assets on the register, none for cement
        self.assertEqual(ToolAsset.objects.filter(site=self.site).count(), 3)
        self.assertEqual(
            ToolAsset.objects.filter(name="Battery drill").count(), 3)
        # cement went to stock; the drill did NOT
        self.assertEqual(StockMovement.objects.filter(item=self.cement).count(),
                         1)
        self.assertFalse(StockMovement.objects.filter(item=self.drill).exists())
        a = ToolAsset.objects.filter(name="Battery drill").first()
        self.assertEqual(a.source, "GRN")
        self.assertEqual(a.brand, "Makita")

    def test_summary_groups_in_use_and_flags_down(self):
        self.verified_grn([(self.drill, 3)])
        assets = list(ToolAsset.objects.filter(name="Battery drill"))
        tools.set_state(assets[0], "FAULTY", "chuck broken", self.sa)
        rows = tools.summary(self.site)
        row = next(r for r in rows if r["item"] == "Battery drill")
        self.assertEqual(row["nos"], 2)                 # 2 still in use
        self.assertIn("1 faulty", row["remarks"])


class ToolsApiTests(ToolsBase):
    def test_add_edit_and_state_cycle(self):
        saw = Item.objects.create(code="ITM-90006", description="Circular saw",
                                  unit="nos", category="Tools & Equipment")
        # manual add (mobilisation) — name/category come from the catalog item
        r = self.client.post(f"/api/v1/tools/{self.site.id}", {
            "item_id": saw.id, "serial_no": "CS-01"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        added = r.data["added"][0]
        aid = added["id"]
        self.assertEqual(added["source"], "MOBILISATION")
        self.assertEqual(added["name"], "Circular saw")
        self.assertEqual(added["category"], "Tools & Equipment")
        self.assertEqual(added["serial_no"], "CS-01")
        # edit details
        r = self.client.patch(f"/api/v1/tools/asset/{aid}",
                             {"model": "HS7601", "serial_no": "CS-02"},
                             format="json")
        self.assertEqual(r.data["model"], "HS7601")
        # faulty needs a note
        r = self.client.post(f"/api/v1/tools/asset/{aid}/state",
                             {"state": "FAULTY"}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.client.post(f"/api/v1/tools/asset/{aid}/state",
                             {"state": "FAULTY", "note": "blade guard"},
                             format="json")
        self.assertEqual(r.data["state"], "FAULTY")
        # send for repair, then back to use
        self.client.post(f"/api/v1/tools/asset/{aid}/state",
                        {"state": "UNDER_REPAIR", "note": "sent to Male"},
                        format="json")
        r = self.client.post(f"/api/v1/tools/asset/{aid}/state",
                            {"state": "IN_USE", "note": "repaired"},
                            format="json")
        self.assertEqual(r.data["state"], "IN_USE")

    def test_edit_can_retype_from_catalog(self):
        """Renaming a unit = re-pointing it at another catalog tool type;
        name + category follow, and the change stays inside the catalog."""
        self.verified_grn([(self.drill, 1)])
        saw = Item.objects.create(code="ITM-90007", description="Circular saw",
                                  unit="nos", category="Tools & Equipment")
        aid = ToolAsset.objects.filter(name="Battery drill").first().id
        r = self.client.patch(f"/api/v1/tools/asset/{aid}",
                             {"item_id": saw.id}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["name"], "Circular saw")
        self.assertEqual(r.data["item_id"], saw.id)
        # a non-tool item is rejected — names stay controlled
        r = self.client.patch(f"/api/v1/tools/asset/{aid}",
                             {"item_id": self.cement.id}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_register_lists_with_counts(self):
        self.verified_grn([(self.drill, 2)])
        r = self.client.get(f"/api/v1/tools/{self.site.id}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data["tools"]), 2)
        self.assertEqual(r.data["counts"].get("IN_USE"), 2)
        self.assertTrue(r.data["can_manage"])

    def test_catalog_lists_only_tool_items(self):
        r = self.client.get("/api/v1/tool-catalog")
        self.assertEqual(r.status_code, 200)
        names = [i["description"] for i in r.data["items"]]
        self.assertIn("Battery drill", names)     # tool category
        self.assertNotIn("Cement", names)         # Civil, not a tool
        self.assertIn("Tools & Equipment", r.data["categories"])

    def test_manual_add_requires_a_catalog_tool(self):
        # free-text name with no catalog item is rejected (controlled)
        r = self.client.post(f"/api/v1/tools/{self.site.id}",
                             {"name": "Anglegrinder"}, format="json")
        self.assertEqual(r.status_code, 400)
        # a non-tool item (cement) is also rejected
        r = self.client.post(f"/api/v1/tools/{self.site.id}",
                             {"item_id": self.cement.id}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_manual_add_name_matches_grn_for_summary(self):
        """Manual + GRN units of the same tool item share one exact name so
        the DPR summary groups them together."""
        self.verified_grn([(self.drill, 1)])
        r = self.client.post(f"/api/v1/tools/{self.site.id}",
                             {"item_id": self.drill.id}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        rows = tools.summary(self.site)
        drill_rows = [x for x in rows if x["item"] == "Battery drill"]
        self.assertEqual(len(drill_rows), 1)      # one grouped row
        self.assertEqual(drill_rows[0]["nos"], 2)  # GRN unit + manual unit


class ToolsNewApproachTests(ToolsBase):
    """Owner 2026-10-01: the category tick was switched off with no trace and
    no site could add a tool for two months, while tools arriving on GRNs
    were booked as counted stock. Tracking is now per item, a site can type a
    tool the catalog lacks, add several at once, and take wrong entries off."""

    def test_an_item_answers_for_itself_over_its_category(self):
        plier = Item.objects.create(code="ITM-90010", description="Plier",
                                    unit="nos", category="Tools & Equipment",
                                    tracked_tool=False)
        genset = Item.objects.create(code="ITM-90011", description="Generator",
                                     unit="nos", category="Civil",
                                     tracked_tool=True)
        self.assertFalse(tools.is_tool_item(plier))
        self.assertTrue(tools.is_tool_item(genset))
        names = [i["description"] for i in
                 self.client.get("/api/v1/tool-catalog").data["items"]]
        self.assertIn("Generator", names)
        self.assertNotIn("Plier", names)
        # a GRN follows the same answer: pliers to stock, generator tracked
        self.verified_grn([(plier, 10), (genset, 1)])
        self.assertEqual(ToolAsset.objects.filter(name="Plier").count(), 0)
        self.assertEqual(ToolAsset.objects.filter(name="Generator").count(), 1)
        self.assertEqual(float(StockMovement.objects.get(item=plier).qty), 10.0)

    def test_tracked_items_survive_the_category_tick_going_off(self):
        self.drill.tracked_tool = True
        self.drill.save(update_fields=["tracked_tool"])
        ItemCategory.objects.filter(name="Tools & Equipment").update(is_tool=False)
        r = self.client.post(f"/api/v1/tools/{self.site.id}",
                             {"item_id": self.drill.id}, format="json")
        self.assertEqual(r.status_code, 201, r.data)

    def test_several_units_at_once(self):
        r = self.client.post(f"/api/v1/tools/{self.site.id}", {
            "item_id": self.drill.id, "qty": 5, "serial_no": "X",
            "brand": "Bosch"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(len(r.data["added"]), 5)
        # one serial cannot belong to five drills
        self.assertEqual({a["serial_no"] for a in r.data["added"]}, {""})
        self.assertEqual({a["brand"] for a in r.data["added"]}, {"Bosch"})
        for bad in (0, 51, "x"):
            self.assertEqual(self.client.post(
                f"/api/v1/tools/{self.site.id}",
                {"item_id": self.drill.id, "qty": bad},
                format="json").status_code, 400)

    def test_a_site_types_a_tool_the_catalog_lacks(self):
        r = self.client.post(f"/api/v1/tools/{self.site.id}",
                             {"new_name": "  Plate   Compactor ", "qty": 2},
                             format="json")
        self.assertEqual(r.status_code, 201, r.data)
        item = Item.objects.get(description="Plate Compactor")
        self.assertEqual((item.category, item.tracked_tool,
                          item.is_provisional),
                         ("Tools & Equipment", True, True))
        # the same name again, in other capitals, reuses it
        r = self.client.post(f"/api/v1/tools/{self.site.id}",
                             {"new_name": "plate compactor"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(Item.objects.filter(
            description__iexact="plate compactor").count(), 1)
        self.assertEqual(ToolAsset.objects.filter(item=item).count(), 3)
        # a name that is already a stock item is not silently duplicated
        r = self.client.post(f"/api/v1/tools/{self.site.id}",
                             {"new_name": "cement"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("stock item", r.data["detail"])

    def test_removing_units_and_returning_them_to_stock(self):
        made = self.client.post(f"/api/v1/tools/{self.site.id}", {
            "item_id": self.drill.id, "qty": 3}, format="json").data["added"]
        ids = [a["id"] for a in made]
        url = f"/api/v1/tools/{self.site.id}/remove"
        self.assertEqual(self.client.post(url, {"ids": ids[:2]},
                                          format="json").status_code, 400)
        r = self.client.post(url, {"ids": ids[:2], "to_stock": True,
                                   "reason": "hand tools"}, format="json")
        self.assertEqual(r.data, {"removed": 2, "kept": []})
        self.assertEqual(ToolAsset.objects.filter(site=self.site).count(), 1)
        from . import stock
        self.assertEqual(float(stock.balance(self.site, self.drill)), 2.0)
        r = self.client.post(url, {"ids": ids[2:], "reason": "entered twice"},
                             format="json")
        self.assertEqual(r.data["removed"], 1)
        self.assertEqual(float(stock.balance(self.site, self.drill)), 2.0)
        # another site's tools are out of reach
        other = Site.objects.create(code="VKR", name="V", status="ACTIVE")
        t = tools.add_units(other, self.drill, 1, self.sa)[0]
        self.assertEqual(self.client.post(url, {"ids": [t.id], "reason": "x"},
                                          format="json").status_code, 400)

    def test_tools_booked_as_stock_move_onto_the_register(self):
        # what the GRNs did while the tick was off
        ItemCategory.objects.filter(name="Tools & Equipment").update(is_tool=False)
        grn = self.verified_grn([(self.drill, 4), (self.cement, 50)])
        self.assertEqual(ToolAsset.objects.count(), 0)
        ItemCategory.objects.filter(name="Tools & Equipment").update(is_tool=True)
        from . import stock
        stock.issue(self.site, None, [{"item": self.drill, "qty": 1}],
                    actor=self.sa)                       # one already handed out
        rows = tools.stock_to_convert()
        self.assertEqual([(r[0].code, r[1].description, r[2], r[3].ref)
                          for r in rows],
                         [("SJR", "Battery drill", 3, grn.ref)])
        moved = tools.convert_stock(self.sa)
        self.assertEqual(sum(m[2] for m in moved), 3)
        assets = ToolAsset.objects.filter(site=self.site)
        self.assertEqual((assets.count(), {a.source for a in assets},
                          {a.document_id for a in assets}),
                         (3, {"STOCK"}, {grn.id}))
        self.assertEqual(float(stock.balance(self.site, self.drill)), 0.0)
        self.assertEqual(float(stock.balance(self.site, self.cement)), 50.0)
        self.assertEqual(tools.stock_to_convert(), [])   # nothing left; safe to re-run
        self.assertEqual(tools.convert_stock(self.sa), [])

    def test_the_category_tick_is_audited(self):
        from .models import AuditLog
        cat = ItemCategory.objects.get(name="Tools & Equipment")
        self.client.force_authenticate(make_user("hop", User.Role.HO_PURCHASING))
        r = self.client.patch(f"/api/v1/item-categories/{cat.id}",
                              {"is_tool": False}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        log = AuditLog.objects.get(event="CATEGORY_TOOL_FLAG_SET")
        self.assertEqual((log.actor.username, log.detail["is_tool"]),
                         ("hop", False))

    def test_purchasing_marks_an_item_tracked_or_not(self):
        self.client.force_authenticate(make_user("hop2", User.Role.HO_PURCHASING))
        r = self.client.patch(f"/api/v1/items/{self.drill.id}",
                              {"tracked_tool": False}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual((r.data["tracked_tool"], r.data["is_tool"]),
                         (False, False))
        r = self.client.get(f"/api/v1/items/{self.cement.id}")
        self.assertEqual((r.data["tracked_tool"], r.data["is_tool"]),
                         (None, False))
        # a site role cannot change it
        self.client.force_authenticate(self.sa)
        self.assertEqual(self.client.patch(
            f"/api/v1/items/{self.drill.id}", {"tracked_tool": True},
            format="json").status_code, 403)
