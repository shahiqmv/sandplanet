"""Several charges of one kind on a shipment.

A port does not bill a container once and stop: handling, then shifting, then
demurrage while it sits. One row per kind meant the second invoice had nowhere
to go, and the second payment could not be raised (owner 2026-08-30)."""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from . import imports as ipr_svc
from .models import (Document, ImportOrder, ImportShipment, ShipmentPayment,
                     Site, Supplier, User)
from .tests import make_user


class MultipleChargesPerKindTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="MLE", name="Head office",
                                        status=Site.Status.ACTIVE,
                                        is_head_office=True)
        self.user = make_user("hop_chg", User.Role.HO_PURCHASING)
        self.supplier = Supplier.objects.create(name="Guangzhou Pumps")
        doc = Document.objects.create(
            doc_type="IPR", ref="IPR-CHG-001", site=self.site,
            doc_date=date.today(), status="AUTHORISED", created_by=self.user)
        self.order = ImportOrder.objects.create(
            document=doc, supplier=self.supplier,
            order_currency="USD",
            exchange_rate=Decimal("15.42"))
        self.shipment = ImportShipment.objects.create(
            order=self.order, seq=1, ref="SHP-001")

    def _charge(self, amount, label="", **extra):
        data = {"amount": str(amount), "currency": "MVR",
                "payee_name": "Maldives Ports Ltd", "label": label}
        data.update(extra)
        return ipr_svc.set_shipment_payment(self.shipment, "PORT", data,
                                            self.user)

    def test_a_second_port_charge_reuses_the_open_row(self):
        """Editing before the PYR is raised must not pile up empty rows."""
        first, err = self._charge(1000, "Handling")
        self.assertIsNone(err)
        again, err = self._charge(1200, "Handling corrected")
        self.assertIsNone(err)
        self.assertEqual(first.id, again.id)
        self.assertEqual(ShipmentPayment.objects.count(), 1)

    def test_new_forces_a_second_charge_of_the_same_kind(self):
        first, _ = self._charge(1000, "Port handling")
        second, err = self._charge(450, "Container shifting", new=True)
        self.assertIsNone(err)
        self.assertNotEqual(first.id, second.id)
        self.assertEqual(
            ShipmentPayment.objects.filter(kind="PORT").count(), 2)

    def test_once_paid_the_next_charge_starts_a_new_row(self):
        """The second invoice from the port has somewhere to go without any
        special action."""
        first, _ = self._charge(1000, "Port handling")
        first.pyr = Document.objects.create(
            doc_type="PYR", ref="PYR-CHG-001", site=self.site,
            doc_date=date.today(), status="SUBMITTED", created_by=self.user)
        first.save(update_fields=["pyr"])
        second, err = self._charge(700, "Demurrage 3 days")
        self.assertIsNone(err)
        self.assertNotEqual(first.id, second.id)

    def test_a_raised_charge_cannot_be_edited_and_says_what_to_do(self):
        first, _ = self._charge(1000)
        first.pyr = Document.objects.create(
            doc_type="PYR", ref="PYR-CHG-002", site=self.site,
            doc_date=date.today(), status="SUBMITTED", created_by=self.user)
        first.save(update_fields=["pyr"])
        _, err = ipr_svc.set_shipment_payment(
            self.shipment, "PORT", {"amount": "9", "charge_id": first.id},
            self.user)
        self.assertIn("Add another charge", err)

    def test_landed_cost_sums_every_charge_of_the_kind(self):
        """Assigning instead of summing would drop the earlier invoices and
        make the material look cheaper than it was."""
        self._charge(1000, "Port handling")
        self._charge(450, "Container shifting", new=True)
        self._charge(700, "Demurrage", new=True)
        self.shipment.refresh_from_db()
        self.assertEqual(self.shipment.port_handling, Decimal("2150.00"))

    def test_a_foreign_currency_charge_converts_before_it_is_summed(self):
        self._charge(1000, "Port handling")
        ipr_svc.set_shipment_payment(
            self.shipment, "PORT",
            {"amount": "100", "currency": "USD", "new": True,
             "payee_name": "MPL"}, self.user)
        self.shipment.refresh_from_db()
        # 1000 MVR + (100 USD x 15.42)
        self.assertEqual(self.shipment.port_handling, Decimal("2542.00"))

    def test_removing_the_amount_leaves_the_rest_counted(self):
        a, _ = self._charge(1000, "Port handling")
        self._charge(450, "Shifting", new=True)
        ipr_svc.set_shipment_payment(
            self.shipment, "PORT", {"amount": "", "charge_id": a.id},
            self.user)
        self.shipment.refresh_from_db()
        self.assertEqual(self.shipment.port_handling, Decimal("450.00"))

    def test_kinds_stay_independent(self):
        self._charge(1000, "Port handling")
        ipr_svc.set_shipment_payment(
            self.shipment, "DUTY", {"amount": "5000", "currency": "MVR",
                                    "payee_name": "Customs"}, self.user)
        self.shipment.refresh_from_db()
        self.assertEqual(self.shipment.port_handling, Decimal("1000.00"))
        self.assertEqual(self.shipment.customs_duty, Decimal("5000.00"))

    def test_a_label_distinguishes_the_rows(self):
        a, _ = self._charge(1000, "Port handling")
        b, _ = self._charge(700, "Demurrage 3 days", new=True)
        self.assertEqual(a.display_label(), "Port handling")
        self.assertEqual(b.display_label(), "Demurrage 3 days")

    def test_an_unlabelled_charge_falls_back_to_its_kind(self):
        a, _ = self._charge(1000)
        self.assertEqual(a.display_label(), a.get_kind_display())
