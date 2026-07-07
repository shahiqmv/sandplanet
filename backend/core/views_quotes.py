"""Suppliers, quotations, matching, coverage, PO generation (DECISIONS.md R2)."""

from decimal import Decimal

from rest_framework import serializers, viewsets
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import BasePermission
from rest_framework.response import Response

from .audit import audit
from .models import Document, DocumentLine, Quotation, QuotationLine, Supplier
from .permissions import scoped_site_ids


class IsPurchasingOrReadOnly(BasePermission):
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True
        return request.user.role in ("HO_PURCHASING", "ADMIN")


class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = ["id", "name", "contact_person", "phone", "email", "address",
                  "notes", "is_active"]


class SupplierViewSet(viewsets.ModelViewSet):
    serializer_class = SupplierSerializer
    permission_classes = [IsPurchasingOrReadOnly]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        qs = Supplier.objects.order_by("name")
        search = self.request.GET.get("search")
        if search:
            qs = qs.filter(name__icontains=search)
        if self.request.GET.get("active") != "all":
            qs = qs.filter(is_active=True)
        return qs

    def perform_create(self, serializer):
        supplier = serializer.save()
        audit("supplier", supplier.id, "SUPPLIER_CREATED",
              actor=self.request.user, detail={"name": supplier.name})


class QuotationLineSerializer(serializers.ModelSerializer):
    mr_line_desc = serializers.SerializerMethodField()

    class Meta:
        model = QuotationLine
        fields = ["id", "line_no", "supplier_desc", "unit", "qty", "rate",
                  "amount", "mr_line", "mr_line_desc", "awarded", "remarks"]

    def get_mr_line_desc(self, obj):
        return obj.mr_line.description if obj.mr_line else None


class QuotationSerializer(serializers.ModelSerializer):
    lines = QuotationLineSerializer(many=True, read_only=True)
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    total = serializers.SerializerMethodField()
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = Quotation
        fields = ["id", "supplier", "supplier_name", "quote_ref", "quote_date",
                  "valid_until", "payment_terms", "notes", "file_url",
                  "total", "lines"]

    def get_total(self, obj):
        return sum((line.amount or 0) for line in obj.lines.all())

    def get_file_url(self, obj):
        if not obj.file:
            return None
        request = self.context.get("request")
        url = obj.file.url
        return request.build_absolute_uri(url) if request else url


def _get_pr(request, ref):
    try:
        pr = Document.objects.get(ref=ref, doc_type="PR", is_void=False)
    except Document.DoesNotExist:
        return None, Response({"detail": "Not found."}, status=404)
    site_ids = scoped_site_ids(request.user)
    if site_ids is not None and pr.site_id not in site_ids:
        return None, Response({"detail": "Not found."}, status=404)
    return pr, None


def _can_edit_quotes(request, pr):
    if request.user.role not in ("HO_PURCHASING", "ADMIN"):
        return Response({"detail": "HO Purchasing manages quotations."},
                        status=403)
    if pr.status not in ("DRAFT", "SUBMITTED"):
        return Response({"detail": "Quotations are editable until the PR is "
                                   "approved."}, status=400)
    return None


def _save_quote_lines(quotation, lines_data):
    quotation.lines.all().delete()
    for i, data in enumerate(lines_data, start=1):
        qty = data.get("qty")
        rate = data.get("rate")
        amount = data.get("amount")
        if amount in (None, "") and qty not in (None, "") and \
                rate not in (None, ""):
            amount = Decimal(str(qty)) * Decimal(str(rate))
        mr_line = None
        if data.get("mr_line"):
            mr_line = DocumentLine.objects.get(pk=data["mr_line"])
        QuotationLine.objects.create(
            quotation=quotation, line_no=i,
            supplier_desc=data.get("supplier_desc", ""),
            unit=data.get("unit", ""),
            qty=Decimal(str(qty)) if qty not in (None, "") else None,
            rate=Decimal(str(rate)) if rate not in (None, "") else None,
            amount=Decimal(str(amount)) if amount not in (None, "") else None,
            mr_line=mr_line,
            awarded=bool(data.get("awarded")),
            remarks=data.get("remarks", ""),
        )


@api_view(["GET", "POST"])
def pr_quotations(request, ref):
    pr, err = _get_pr(request, ref)
    if err:
        return err
    if request.method == "GET":
        qs = pr.quotations.select_related("supplier").prefetch_related(
            "lines__mr_line__item")
        return Response(QuotationSerializer(qs, many=True,
                                            context={"request": request}).data)
    err = _can_edit_quotes(request, pr)
    if err:
        return err
    try:
        supplier = Supplier.objects.get(pk=request.data.get("supplier"),
                                        is_active=True)
    except Supplier.DoesNotExist:
        return Response({"detail": "supplier must be an active supplier id."},
                        status=400)
    quotation = Quotation.objects.create(
        document=pr, supplier=supplier,
        quote_ref=request.data.get("quote_ref", ""),
        quote_date=request.data.get("quote_date") or None,
        valid_until=request.data.get("valid_until") or None,
        payment_terms=request.data.get("payment_terms", ""),
        notes=request.data.get("notes", ""),
        created_by=request.user,
    )
    _save_quote_lines(quotation, request.data.get("lines") or [])
    audit("quotation", quotation.id, "QUOTATION_ADDED", actor=request.user,
          detail={"pr": pr.ref, "supplier": supplier.name})
    return Response(QuotationSerializer(quotation,
                                        context={"request": request}).data,
                    status=201)


@api_view(["PATCH", "DELETE"])
def quotation_detail(request, pk):
    try:
        quotation = Quotation.objects.select_related("document",
                                                     "supplier").get(pk=pk)
    except Quotation.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    err = _can_edit_quotes(request, quotation.document)
    if err:
        return err
    if request.method == "DELETE":
        quotation.lines.all().delete()
        quotation.delete()
        audit("quotation", pk, "QUOTATION_REMOVED", actor=request.user)
        return Response(status=204)
    for field in ("quote_ref", "quote_date", "valid_until", "payment_terms",
                  "notes"):
        if field in request.data:
            setattr(quotation, field, request.data[field] or None
                    if field.endswith("date") or field == "valid_until"
                    else request.data[field])
    quotation.save()
    if "lines" in request.data:
        _save_quote_lines(quotation, request.data["lines"])
    return Response(QuotationSerializer(quotation,
                                        context={"request": request}).data)


@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser])
def quotation_file(request, pk):
    try:
        quotation = Quotation.objects.select_related("document").get(pk=pk)
    except Quotation.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    err = _can_edit_quotes(request, quotation.document)
    if err:
        return err
    upload = request.FILES.get("file")
    if upload is None:
        return Response({"detail": "file is required."}, status=400)
    quotation.file = upload
    quotation.save(update_fields=["file"])
    return Response(QuotationSerializer(quotation,
                                        context={"request": request}).data)


def pr_coverage_data(pr):
    """Per MR line: how many quote lines match it, and the awarded ones.
    The tally that closes the MR→manifest vacuum (R2)."""
    mr_docs = [link.to_document for link in
               pr.links_from.filter(link_type="MR_PR")
               .select_related("to_document")]
    matches = {}
    for ql in QuotationLine.objects.filter(
        quotation__document=pr, mr_line__isnull=False
    ).select_related("quotation__supplier"):
        matches.setdefault(ql.mr_line_id, []).append(ql)
    rows = []
    for mr in mr_docs:
        for line in mr.current_revision.lines.select_related("item"):
            quote_lines = matches.get(line.id, [])
            rows.append({
                "mr_ref": mr.ref,
                "mr_line_id": line.id,
                "description": line.description,
                "unit": line.unit,
                "qty_to_order": line.qty_to_order,
                "quoted_by": [
                    {"supplier": ql.quotation.supplier.name,
                     "qty": ql.qty, "rate": ql.rate, "awarded": ql.awarded}
                    for ql in quote_lines
                ],
                "covered": bool(quote_lines),
                "awarded": any(ql.awarded for ql in quote_lines),
            })
    return rows


@api_view(["GET"])
def pr_coverage(request, ref):
    pr, err = _get_pr(request, ref)
    if err:
        return err
    rows = pr_coverage_data(pr)
    return Response({
        "pr": pr.ref,
        "rows": rows,
        "uncovered": [r["description"] for r in rows if not r["covered"]],
        "unawarded": [r["description"] for r in rows if r["covered"]
                      and not r["awarded"]],
    })


@api_view(["POST"])
def pr_sync_vendor_rows(request, ref):
    """Rebuild the PR vendor-summary rows from captured quotations, so the
    Director approves totals backed by item-level detail (R2)."""
    pr, err = _get_pr(request, ref)
    if err:
        return err
    err = _can_edit_quotes(request, pr)
    if err:
        return err
    if pr.status != "DRAFT":
        return Response({"detail": "Sync vendor rows while the PR is a draft."},
                        status=400)
    revision = pr.current_revision
    revision.lines.all().delete()
    for i, quotation in enumerate(
        pr.quotations.select_related("supplier").prefetch_related("lines"),
        start=1,
    ):
        total = sum((line.amount or 0) for line in quotation.lines.all())
        is_credit = "credit" in (quotation.payment_terms or "").lower()
        DocumentLine.objects.create(
            revision=revision, line_no=i,
            free_text_desc=quotation.supplier.name,
            vendor=quotation.supplier.name,
            quotation_ref=quotation.quote_ref,
            payment_terms=quotation.payment_terms,
            amount_cash=None if is_credit else total,
            amount_credit=total if is_credit else None,
        )
    audit("document", pr.id, "PR_VENDOR_ROWS_SYNCED", actor=request.user,
          detail={"ref": pr.ref})
    from .serializers_documents import DocumentSerializer

    return Response(DocumentSerializer(pr, context={"request": request}).data)
