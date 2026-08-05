"""Project bonds & insurance — capture → PYR → paid → issued → expiry."""
from datetime import date, timedelta

from django.test import TestCase

from . import bonds
from .models import Project, ProjectBond, Site, User
from .tests import make_user


class BondTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="VKR", name="Vakkaru",
                                        status=Site.Status.ACTIVE)
        self.qs = make_user("bond_qs", User.Role.QS)
        self.director = make_user("bond_dir", User.Role.DIRECTOR)
        self.se = make_user("bond_se", User.Role.SITE_ENGINEER, site=self.site)
        self.project = Project.objects.create(
            site=self.site, code="VKR-01", title="Pools", qs=self.qs)

    def test_lifecycle(self):
        bond, err = bonds.add_bond(
            self.project,
            {"kind": "PB", "required": True, "insurer": "Allied Insurance",
             "premium": "12000"}, None, self.qs)
        self.assertIsNone(err)
        self.assertEqual(bond.status, ProjectBond.Status.QUOTED)
        # raise the premium PYR
        self.assertIsNone(bonds.raise_bond_pyr(bond, self.qs))
        bond.refresh_from_db()
        self.assertEqual(bond.status, ProjectBond.Status.PAYMENT_RAISED)
        self.assertIsNotNone(bond.pyr_id)
        self.assertEqual(bond.pyr.doc_type, "PYR")
        # commercial premium — no PM/Director; auto-cleared straight to Finance
        self.assertEqual(bond.pyr.payment_request.origin, "COMMERCIAL")
        self.assertEqual(bond.pyr.status, "DIRECTOR_APPROVED")
        # can't raise twice
        self.assertIsNotNone(bonds.raise_bond_pyr(bond, self.qs))
        # paying the PYR flips the cover to PAID
        bonds.on_pyr_paid(bond.pyr, self.director)
        bond.refresh_from_db()
        self.assertEqual(bond.status, ProjectBond.Status.PAID)
        # issue the policy
        self.assertIsNone(bonds.issue_bond(
            bond, {"policy_ref": "POL-9",
                   "expiry_date": (date.today() + timedelta(days=200)
                                   ).isoformat()}, None, self.qs))
        bond.refresh_from_db()
        self.assertEqual(bond.status, ProjectBond.Status.ISSUED)

    def test_required_gaps(self):
        bonds.add_bond(self.project,
                       {"kind": "PB", "required": True, "premium": "1"},
                       None, self.qs)
        self.assertIn("Performance Bond", bonds.required_gaps(self.project))
        bonds.add_bond(self.project, {"kind": "CAR", "required": False},
                       None, self.qs)
        self.assertNotIn("Contractor's All-Risk Insurance",
                         bonds.required_gaps(self.project))

    def test_role_gate(self):
        _, err = bonds.add_bond(self.project, {"kind": "PB"}, None, self.se)
        self.assertIsNotNone(err)

    def test_expiry_sweep_watermarks(self):
        bond, _ = bonds.add_bond(self.project, {"kind": "PB", "premium": "1"},
                                 None, self.qs)
        bond.status = ProjectBond.Status.ISSUED
        bond.expiry_date = date.today() + timedelta(days=5)   # within T7
        bond.save()
        self.assertGreaterEqual(bonds.sweep_bond_expiry(), 1)
        bond.refresh_from_db()
        self.assertEqual(bond.expiry_alert, "T7")
        self.assertEqual(bonds.sweep_bond_expiry(), 0)        # no re-fire
