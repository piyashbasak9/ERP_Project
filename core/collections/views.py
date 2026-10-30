import uuid
from datetime import date
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from core.common.popup import popup_json_response, render_popup_form

from .forms import (
    CancellationForm,
    CollectionEntryForm,
    CollectionSheetForm,
    ReconciliationForm,
)
from .models import CollectionSheet, CollectionSheetItem
from .services import CollectionService

ZERO = Decimal("0.00")


@require_GET
def sheet_list(request):
    queryset = CollectionSheet.objects.select_related(
        "branch", "center", "group", "field_officer"
    )
    status = request.GET.get("status", "")
    if status in dict(CollectionSheet.STATUS_CHOICES):
        queryset = queryset.filter(status=status)
    search = request.GET.get("searchString", "").strip()
    if search:
        queryset = queryset.filter(
            Q(center__name__icontains=search)
            | Q(center__code__icontains=search)
            | Q(field_officer__full_name__icontains=search)
            | Q(group__name__icontains=search)
        )
    if request.GET.get("format") == "json":
        page = max(1, int(request.GET.get("page", 1)))
        page_size = min(100, max(1, int(request.GET.get("rows", 25))))
        paginator = Paginator(queryset.order_by("-collection_date", "-pk"), page_size)
        page_obj = paginator.get_page(page)
        return JsonResponse(
            {
                "page": page_obj.number,
                "total": paginator.num_pages,
                "records": paginator.count,
                "rows": [
                    {
                        "id": sheet.pk,
                        "center": sheet.center.name,
                        "group": sheet.group.name if sheet.group_id else "",
                        "field_officer": sheet.field_officer.full_name,
                        "collection_date": sheet.collection_date.isoformat(),
                        "status": sheet.get_status_display(),
                        "status_key": sheet.status,
                        "total_collected": str(_sheet_total(sheet)),
                        "detail_url": reverse(
                            "collections:Module_Collections_sheet_detail",
                            args=[sheet.pk],
                        ),
                    }
                    for sheet in page_obj
                ],
            }
        )
    return render(
        request,
        "collections/sheet_list.html",
        {
            "statuses": CollectionSheet.STATUS_CHOICES,
            "selected_status": status,
        },
    )


@require_http_methods(["GET", "POST"])
def sheet_generate(request):
    form = CollectionSheetForm(request.POST or None, request=request)
    if request.method == "POST" and form.is_valid():
        values = form.cleaned_data
        try:
            sheet = CollectionService(request).generate(
                center_id=values["center"].pk,
                group_id=values["group"].pk if values["group"] else None,
                field_officer_id=(
                    values["field_officer"].pk if values["field_officer"] else None
                ),
                collection_date=values["collection_date"],
                idempotency_key=values["idempotency_key"],
            )
        except ValidationError as error:
            _add_validation_error(form, error)
        else:
            response = popup_json_response(
                request,
                message="Collection sheet generated.",
                data={"id": sheet.pk, "url": reverse(
                    "collections:Module_Collections_sheet_detail", args=[sheet.pk]
                )},
            )
            if response is not None:
                return response
            return redirect(
                "collections:Module_Collections_sheet_detail", pk=sheet.pk
            )
    return render_popup_form(
        request,
        "collections/sheet_generate_form.html",
        {"form": form, "title": "Generate collection sheet"},
        status=400 if request.method == "POST" else 200,
    )


@require_GET
def sheet_detail(request, pk):
    sheet = get_object_or_404(
        CollectionSheet.objects.select_related(
            "center", "group", "field_officer", "generated_by", "reconciled_by"
        ).prefetch_related("items__member"),
        pk=pk,
    )
    can_enter = (
        request.user.is_superuser
        or sheet.branch.branch_manager_id
        and sheet.branch.branch_manager.user_id == request.user.pk
        or sheet.field_officer.user_id == request.user.pk
    )
    return render(
        request,
        "collections/sheet_detail.html",
        {
            "sheet": sheet,
            "items": sheet.items.select_related("member").order_by("member__member_code"),
            "can_enter": can_enter,
            "total_collected": _sheet_total(sheet),
        },
    )


@require_POST
def sheet_start(request, pk):
    return _service_action(
        request,
        lambda: CollectionService(request).start(sheet_id=pk),
        "Collection entry started.",
        redirect_name="collections:Module_Collections_sheet_detail",
        redirect_args=[pk],
    )


@require_POST
def sheet_entry(request, pk, item_pk):
    form = CollectionEntryForm(request.POST)
    if not form.is_valid():
        return _json_error("Please correct the collection amounts.", _form_errors(form), 400)
    try:
        item = CollectionService(request).record_collection(
            sheet_id=pk,
            item_id=item_pk,
            collected_amount=form.cleaned_data["collected_amount"],
            savings_amount=form.cleaned_data["savings_amount"],
            reason=form.cleaned_data["reason"],
        )
    except CollectionSheet.DoesNotExist:
        from django.http import Http404

        raise Http404
    except (CollectionSheetItem.DoesNotExist, ValidationError) as error:
        return _json_error("Collection entry could not be saved.", _error_detail(error), 400)
    return JsonResponse(
        _envelope(
            "Collection entry saved.",
            data={
                "id": item.pk,
                "collected_amount": str(item.collected_amount),
                "savings_amount": str(item.savings_amount),
            },
        )
    )


@require_POST
def sheet_submit(request, pk):
    return _service_action(
        request,
        lambda: CollectionService(request).submit(sheet_id=pk),
        "Collection sheet submitted.",
        redirect_name="collections:Module_Collections_sheet_detail",
        redirect_args=[pk],
    )


@require_GET
def reconciliation_list(request):
    queryset = CollectionSheet.objects.select_related(
        "center", "field_officer", "generated_by"
    ).filter(
        status__in=[
            CollectionSheet.STATUS_SUBMITTED,
            CollectionSheet.STATUS_RECONCILED,
            CollectionSheet.STATUS_POSTED,
        ]
    )
    sheets = [
        {"sheet": sheet, "collected": _sheet_total(sheet)}
        for sheet in queryset
    ]
    return render(request, "collections/reconciliation_list.html", {"sheets": sheets})


@require_POST
def sheet_reconcile(request, pk):
    form = ReconciliationForm(request.POST)
    if not form.is_valid():
        return _json_error("Enter the cash received.", _form_errors(form), 400)
    try:
        sheet = CollectionService(request).reconcile(
            sheet_id=pk, cash_received=form.cleaned_data["cash_received"]
        )
    except CollectionSheet.DoesNotExist:
        from django.http import Http404

        raise Http404
    except ValidationError as error:
        return _json_error("Collection sheet could not be reconciled.", _error_detail(error), 400)
    except PermissionDenied as error:
        return _json_error(str(error), {}, 403)
    return JsonResponse(
        _envelope(
            "Collection sheet reconciled.",
            data={
                "id": sheet.pk,
                "status": sheet.status,
                "shortage": str(sheet.cash_shortage),
                "excess": str(sheet.cash_excess),
            },
        )
    )


@require_POST
def sheet_post(request, pk):
    try:
        key = request.POST.get("idempotency_key") or request.headers.get(
            "Idempotency-Key"
        )
        sheet = CollectionService(request).post(sheet_id=pk, idempotency_key=key)
    except CollectionSheet.DoesNotExist:
        from django.http import Http404

        raise Http404
    except ValidationError as error:
        return _json_error("Collection sheet could not be posted.", _error_detail(error), 400)
    except PermissionDenied as error:
        return _json_error(str(error), {}, 403)
    response = _json_response(
        request,
        "Collection sheet posted to the ledger.",
        data={"id": sheet.pk, "status": sheet.status},
    )
    if response is not None:
        return response
    return redirect("collections:Module_Collections_sheet_detail", pk=sheet.pk)


@require_POST
def sheet_cancel(request, pk):
    form = CancellationForm(request.POST)
    if not form.is_valid():
        return _json_error("A cancellation reason is required.", _form_errors(form), 400)
    try:
        sheet = CollectionService(request).cancel(
            sheet_id=pk, reason=form.cleaned_data["reason"]
        )
    except CollectionSheet.DoesNotExist:
        from django.http import Http404

        raise Http404
    except ValidationError as error:
        return _json_error("Collection sheet could not be cancelled.", _error_detail(error), 400)
    return _json_response(
        request,
        "Collection sheet cancelled.",
        data={"id": sheet.pk, "status": sheet.status},
    ) or redirect("collections:Module_Collections_sheet_detail", pk=sheet.pk)


@require_GET
def sheet_print(request, pk):
    sheet = get_object_or_404(
        CollectionSheet.objects.select_related("center", "group", "field_officer"),
        pk=pk,
    )
    return render(
        request,
        "collections/sheet_print.html",
        {
            "sheet": sheet,
            "items": sheet.items.select_related("member").order_by("member__member_code"),
            "total_collected": _sheet_total(sheet),
        },
    )


def _report_queryset(request):
    queryset = CollectionSheet.objects.select_related(
        "center", "field_officer", "group"
    ).filter(status=CollectionSheet.STATUS_POSTED)
    raw_date = request.GET.get("date", "")
    if raw_date:
        try:
            selected_date = date.fromisoformat(raw_date)
        except ValueError:
            selected_date = timezone.localdate()
    else:
        selected_date = timezone.localdate()
    return queryset.filter(collection_date=selected_date), selected_date


def _report_rows(queryset):
    rows = []
    for sheet in queryset:
        rows.append(
            {
                "sheet": sheet,
                "due": sheet.items.aggregate(
                    total=Sum("expected_installment")
                    + Sum("expected_overdue")
                    + Sum("expected_penalty")
                    + Sum("expected_savings")
                )["total"]
                or ZERO,
                "collected": _sheet_total(sheet),
            }
        )
    return rows


@require_GET
def report_daily(request):
    queryset, selected_date = _report_queryset(request)
    rows = _report_rows(queryset)
    return render(
        request,
        "collections/report.html",
        {
            "title": "Daily collection summary",
            "selected_date": selected_date,
            "rows": rows,
            "total_due": sum((row["due"] for row in rows), ZERO),
            "total_collected": sum((row["collected"] for row in rows), ZERO),
            "total_shortage": sum((row["sheet"].cash_shortage for row in rows), ZERO),
            "total_excess": sum((row["sheet"].cash_excess for row in rows), ZERO),
            "report_type": "daily",
        },
    )


@require_GET
def report_performance(request):
    queryset, selected_date = _report_queryset(request)
    rows = _report_rows(queryset)
    grouped = {}
    for row in rows:
        officer = row["sheet"].field_officer.full_name
        grouped.setdefault(officer, {"officer": officer, "sheets": 0, "collected": ZERO})
        grouped[officer]["sheets"] += 1
        grouped[officer]["collected"] += row["collected"]
    return render(
        request,
        "collections/report.html",
        {
            "title": "Collector performance",
            "selected_date": selected_date,
            "rows": list(grouped.values()),
            "report_type": "performance",
        },
    )


@require_GET
def report_efficiency(request):
    queryset, selected_date = _report_queryset(request)
    rows = _report_rows(queryset)
    for row in rows:
        row["efficiency"] = (
            row["collected"] / row["due"] * Decimal(100)
            if row["due"]
            else ZERO
        )
    return render(
        request,
        "collections/report.html",
        {
            "title": "Collection efficiency",
            "selected_date": selected_date,
            "rows": rows,
            "report_type": "efficiency",
        },
    )


@require_GET
def report_variances(request):
    queryset, selected_date = _report_queryset(request)
    rows = _report_rows(queryset)
    return render(
        request,
        "collections/report.html",
        {
            "title": "Collection shortages and excesses",
            "selected_date": selected_date,
            "rows": rows,
            "report_type": "variances",
        },
    )


@require_GET
def report_excel(request):
    queryset, selected_date = _report_queryset(request)
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Collections"
    sheet.append(
        [
            "Date",
            "Branch",
            "Center",
            "Group",
            "Field officer",
            "Due",
            "Collected",
            "Cash received",
            "Shortage",
            "Excess",
        ]
    )
    for row in _report_rows(queryset):
        record = row["sheet"]
        sheet.append(
            [
                record.collection_date.isoformat(),
                record.branch.code,
                record.center.name,
                record.group.name if record.group_id else "",
                record.field_officer.full_name,
                float(row["due"]),
                float(row["collected"]),
                float(record.cash_received or ZERO),
                float(record.cash_shortage),
                float(record.cash_excess),
            ]
        )
    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = (
        f'attachment; filename="collections-{selected_date.isoformat()}.xlsx"'
    )
    workbook.save(response)
    return response


@require_GET
def report_pdf(request):
    queryset, selected_date = _report_queryset(request)
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import landscape, letter
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = (
        f'attachment; filename="collections-{selected_date.isoformat()}.pdf"'
    )
    document = SimpleDocTemplate(response, pagesize=landscape(letter))
    data = [["Center", "Collector", "Due", "Collected", "Cash", "Shortage", "Excess"]]
    for row in _report_rows(queryset):
        record = row["sheet"]
        data.append(
            [
                record.center.name,
                record.field_officer.full_name,
                f'{row["due"]:.2f}',
                f'{row["collected"]:.2f}',
                f'{(record.cash_received or ZERO):.2f}',
                f"{record.cash_shortage:.2f}",
                f"{record.cash_excess:.2f}",
            ]
        )
    table = Table(data, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#183153")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                ("PADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    document.build([table])
    return response


def _service_action(request, operation, message, *, redirect_name, redirect_args):
    try:
        result = operation()
    except CollectionSheet.DoesNotExist:
        from django.http import Http404

        raise Http404
    except ValidationError as error:
        return _json_error(message, _error_detail(error), 400)
    return _json_response(
        request, message, data={"id": result.pk, "status": result.status}
    ) or redirect(redirect_name, args=redirect_args)


def _sheet_total(sheet):
    return sheet.items.aggregate(
        total=Sum("collected_amount") + Sum("savings_amount")
    )["total"] or ZERO


def _add_validation_error(form, error):
    if hasattr(error, "message_dict"):
        for field, errors in error.message_dict.items():
            for message in errors:
                form.add_error(field if field in form.fields else None, message)
    else:
        for message in error.messages:
            form.add_error(None, message)


def _error_detail(error):
    if isinstance(error, ValidationError):
        if hasattr(error, "message_dict"):
            return error.message_dict
        return {"__all__": error.messages}
    return {"__all__": [str(error)]}


def _form_errors(form):
    return {
        name: [str(error) for error in errors]
        for name, errors in form.errors.items()
    }


def _envelope(message, *, data=None, errors=None):
    return {
        "success": errors is None,
        "message": message,
        "data": data,
        "errors": errors,
        "request_id": uuid.uuid4().hex[:10],
    }


def _json_error(message, errors, status):
    return JsonResponse(_envelope(message, errors=errors), status=status)


def _json_response(request, message, *, data):
    if (
        request.headers.get("Accept", "").startswith("application/json")
        or request.headers.get("x-requested-with") == "XMLHttpRequest"
    ):
        return JsonResponse(_envelope(message, data=data))
    return None
