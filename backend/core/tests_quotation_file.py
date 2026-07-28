"""Two quotations from the same supplier on one PR must not share a storage
key (S3 file_overwrite=True would otherwise clobber one — owner 2026-07-27)."""
from datetime import date

from django.test import TestCase

from .models import (Document, Quotation, Site, Supplier, User,
                     quotation_path)
from .tests import make_user


class QuotationFilePathTests(TestCase):
    def test_same_supplier_quotes_get_distinct_paths(self):
        user = make_user("qf_buy", User.Role.HO_PURCHASING)
        site = Site.objects.create(code="SJR", name="Jani",
                                   status=Site.Status.ACTIVE)
        pr = Document.objects.create(
            doc_type="PR", ref="PR-SJR-001", site=site, doc_date=date.today(),
            status="DRAFT", created_by=user)
        sup = Supplier.objects.create(name="EI&Z Investement",
                                      category="LOCAL")
        q1 = Quotation.objects.create(document=pr, supplier=sup,
                                      created_by=user)
        q2 = Quotation.objects.create(document=pr, supplier=sup,
                                      created_by=user)
        # same filename, same supplier, same PR — the classic collision
        p1 = quotation_path(q1, "quotation.pdf")
        p2 = quotation_path(q2, "quotation.pdf")
        self.assertNotEqual(p1, p2)
        self.assertIn(f"q{q1.pk}-", p1)
        self.assertIn(f"q{q2.pk}-", p2)
