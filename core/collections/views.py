import uuid
from datetime import date
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.html import format_html
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from core.accounts.permission_utils import user_has_route_permission
from core.common.popup import popup_json_response, render_popup_form

from .forms import (
    CancellationForm,
    CollectionEntryForm,
    CollectionSheetForm,
    ReconciliationForm,
    ReversalRequestForm,
)
from .models import (
    CollectionSheet,
    CollectionSheetItem,
    CollectionSheetReversal,
)
from .services import CollectionService

ZERO = Decimal("0.00")


def _collections_grid_page(
    request, queryset, order_fields, default_sort, default_order="asc"
):
    order = order_fields.get(request.GET.get("sidx", default_sort), default_sort)
    sort_order = request.GET.get("sord", default_order).lower()
    if sort_order not in {"asc", "desc"}:
        sort_order = default_order
    if sort_order == "desc":
        order = f"-{order}"
    try:
        page_size = min(max(int(request.GET.get("rows", 20)), 1), 200)
    except (TypeError, ValueError):
        page_size = 20
    paginator = Paginator(queryset.order_by(order, "-pk"), page_size)
    return paginator, paginator.get_page(request.GET.get("page", 1))


@require_GET
def sheet_list(request):
    queryset = CollectionSheet.objects.select_related(
        "branch", "center", "group", "field_officer"
    ).annotate(
        total_collected=Sum("items__collected_amount")
        + Sum("items__savings_amount")
    )
    status = request.GET.get("status", "").strip()
    if status in dict(CollectionSheet.STATUS_CHOICES):
        queryset = queryset.filter(status=status)
    search = request.GET.get(
        "search", request.GET.get("searchString", "")
    ).strip()
    if search:
        queryset = queryset.filter(
            Q(center__name__icontains=search)
            | Q(center__code__icontains=search)
            | Q(field_officer__full_name__icontains=search)
            | Q(group__name__icontains=search)
        )
    if request.GET.get("ajax") == "1" or request.GET.get("format") == "json":
        order_fields = {
            "collection_date": "collection_date",
            "center": "center__name",
            "group": "group__name",
            "field_officer": "field_officer__full_name",
            "status": "status",
        }
        paginator, page_obj = _collections_grid_page(
            request, queryset, order_fields, "collection_date", "desc"
        )
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
                        "total_collected": str(sheet.total_collected or ZERO),
                        "detail_url": reverse(
                            "collections:Module_Collections_sheet_detail",
                            args=[sheet.pk],
                        ),
                        "actions": format_html(
                            '<a class="btn btn-sm btn-outline-primary" href="{}">Open</a>',
                            reverse(
                                "collections:Module_Collections_sheet_detail",
                                args=[sheet.pk],
                            ),
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
            "grid_url": request.path,
            "list_title": "Collection sheets",
            "filter_layout": "members",
            "default_sort_name": "collection_date",
            "default_sort_order": "desc",
            "initial_page_text": "Page 1 of 1",
            "list_actions": [],
            "add_url": (
                reverse("collections:Module_Collections_sheet_generate")
                if user_has_route_permission(
                    request.user, "Module_Collections_sheet_generate"
                )
                else ""
            ),
            "add_title": "Generate sheet",
            "list_filters": [
                {
                    "name": "search",
                    "label": "Search",
                    "value": search,
                    "placeholder": "Center, group, or field officer",
                },
                {
                    "name": "status",
                    "label": "Status",
                    "type": "select",
                    "value": status,
                    "options": CollectionSheet.STATUS_CHOICES,
                },
            ],
            "list_columns": [
                {"name": "collection_date", "label": "Date", "width": 120},
                {"name": "center", "label": "Center", "width": 180},
                {"name": "group", "label": "Group", "width": 140},
                {
                    "name": "field_officer",
                    "label": "Field officer",
                    "width": 180,
                },
                {"name": "status", "label": "Status", "width": 120},
                {
                    "name": "total_collected",
                    "label": "Collected",
                    "width": 140,
                    "align": "right",
                    "sortable": False,
                },
                {
                    "name": "actions",
                    "label": "Open",
                    "width": 90,
                    "sortable": False,
                },
            ],
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
            "reversal_record": CollectionSheetReversal.objects.filter(
                sheet=sheet
            ).select_related("requested_by", "approval_record__approved_by").first(),
            "reversal_form": ReversalRequestForm(
                initial={
                    "reversal_date": sheet.branch.business_date,
                    "idempotency_key": uuid.uuid4(),
                }
            ),
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
    ).annotate(
        total_collected=Sum("items__collected_amount")
        + Sum("items__savings_amount")
    )
    search = request.GET.get("search", "").strip()
    status = request.GET.get("status", "").strip()
    date_from = request.GET.get("date_from", "").strip()
    date_to = request.GET.get("date_to", "").strip()
    if search:
        queryset = queryset.filter(
            Q(center__name__icontains=search)
            | Q(center__code__icontains=search)
            | Q(field_officer__full_name__icontains=search)
            | Q(group__name__icontains=search)
        )
    if status in {
        CollectionSheet.STATUS_SUBMITTED,
        CollectionSheet.STATUS_RECONCILED,
        CollectionSheet.STATUS_POSTED,
    }:
        queryset = queryset.filter(status=status)
    try:
        parsed_date_from = parse_date(date_from) if date_from else None
        parsed_date_to = parse_date(date_to) if date_to else None
    except ValueError:
        return HttpResponseBadRequest("Dates must use YYYY-MM-DD format.")
    if (date_from and parsed_date_from is None) or (
        date_to and parsed_date_to is None
    ):
        return HttpResponseBadRequest("Dates must use YYYY-MM-DD format.")
    if parsed_date_from and parsed_date_to and parsed_date_from > parsed_date_to:
        return HttpResponseBadRequest(
            "The start date must be on or before the end date."
        )
    if parsed_date_from:
        queryset = queryset.filter(collection_date__gte=parsed_date_from)
    if parsed_date_to:
        queryset = queryset.filter(collection_date__lte=parsed_date_to)

    if request.GET.get("ajax") == "1":
        order_fields = {
            "collection_date": "collection_date",
            "center": "center__name",
            "field_officer": "field_officer__full_name",
            "status": "status",
        }
        paginator, page_obj = _collections_grid_page(
            request, queryset, order_fields, "collection_date", "desc"
        )
        rows = []
        token = get_token(request)
        for sheet in page_obj:
            if sheet.status == CollectionSheet.STATUS_SUBMITTED:
                actions = format_html(
                    '<form method="post" action="{}" data-reconcile-form '
                    'class="d-flex gap-2 align-items-center">'
                    '<input type="hidden" name="csrfmiddlewaretoken" value="{}">'
                    '<input class="form-control form-control-sm" name="cash_received" '
                    'type="number" min="0" step="0.01" required aria-label="Cash received">'
                    '<button class="btn btn-sm btn-primary" type="submit">Reconcile</button>'
                    "</form>",
                    reverse(
                        "collections:Module_Collections_sheet_reconcile",
                        args=[sheet.pk],
                    ),
                    token,
                )
            elif sheet.status == CollectionSheet.STATUS_RECONCILED:
                actions = format_html(
                    '<span class="small me-2">Cash {}, shortage {}, excess {}</span>'
                    '<form method="post" action="{}" data-reconcile-form class="d-inline">'
                    '<input type="hidden" name="csrfmiddlewaretoken" value="{}">'
                    '<input type="hidden" name="idempotency_key" value="{}">'
                    '<button class="btn btn-sm btn-success" type="submit">Post</button>'
                    "</form>",
                    sheet.cash_received,
                    sheet.cash_shortage,
                    sheet.cash_excess,
                    reverse(
                        "collections:Module_Collections_sheet_post",
                        args=[sheet.pk],
                    ),
                    token,
                    sheet.idempotency_key,
                )
            else:
                actions = format_html(
                    '<a class="btn btn-sm btn-outline-primary" href="{}">View</a>',
                    reverse(
                        "collections:Module_Collections_sheet_detail",
                        args=[sheet.pk],
                    ),
                )
            rows.append(
                {
                    "id": sheet.pk,
                    "collection_date": sheet.collection_date.isoformat(),
                    "center": sheet.center.name,
                    "field_officer": sheet.field_officer.full_name,
                    "status": sheet.get_status_display(),
                    "collected": str(sheet.total_collected or ZERO),
                    "actions": actions,
                }
            )
        return JsonResponse(
            {
                "rows": rows,
                "page": page_obj.number,
                "total": paginator.num_pages,
                "records": paginator.count,
            }
        )

    return render(
        request,
        "collections/reconciliation_list.html",
        {
            "grid_url": request.path,
            "list_title": "Cash reconciliation",
            "filter_layout": "members",
            "default_sort_name": "collection_date",
            "default_sort_order": "desc",
            "initial_page_text": "Page 1 of 1",
            "list_actions": [],
            "add_url": "",
            "add_title": "",
            "list_filters": [
                {
                    "name": "search",
                    "label": "Search",
                    "value": search,
                    "placeholder": "Center, group, or field officer",
                },
                {
                    "name": "status",
                    "label": "Status",
                    "type": "select",
                    "value": status,
                    "options": (
                        (CollectionSheet.STATUS_SUBMITTED, "Submitted"),
                        (CollectionSheet.STATUS_RECONCILED, "Reconciled"),
                        (CollectionSheet.STATUS_POSTED, "Posted"),
                    ),
                },
                {
                    "name": "collection_date",
                    "label": "Collection date",
                    "type": "date-range",
                    "from_name": "date_from",
                    "from_value": date_from,
                    "to_name": "date_to",
                    "to_value": date_to,
                },
            ],
            "list_columns": [
                {"name": "collection_date", "label": "Date", "width": 120},
                {"name": "center", "label": "Center", "width": 180},
                {
                    "name": "field_officer",
                    "label": "Field officer",
                    "width": 180,
                },
                {"name": "status", "label": "Status", "width": 120},
                {
                    "name": "collected",
                    "label": "Collected",
                    "width": 140,
                    "align": "right",
                    "sortable": False,
                },
                {
                    "name": "actions",
                    "label": "Cash received / posting",
                    "width": 360,
                    "sortable": False,
                },
            ],
        },
    )


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


@require_POST
def sheet_reversal_request(request, pk):
    form = ReversalRequestForm(request.POST)
    if not form.is_valid():
        return _json_error(
            "Provide a reversal date and reason.",
            _form_errors(form),
            400,
        )
    try:
        reversal = CollectionService(request).request_reversal(
            sheet_id=pk,
            reversal_date=form.cleaned_data["reversal_date"],
            reason=form.cleaned_data["reason"],
            idempotency_key=form.cleaned_data["idempotency_key"],
        )
    except CollectionSheet.DoesNotExist:
        from django.http import Http404

        raise Http404
    except ValidationError as error:
        return _json_error("Collection reversal could not be requested.", _error_detail(error), 400)
    except PermissionDenied as error:
        return _json_error(str(error), {}, 403)
    return _json_response(
        request,
        "Collection reversal requested for checker approval.",
        data={"id": reversal.pk, "status": reversal.status},
    ) or redirect("collections:Module_Collections_sheet_detail", pk=pk)


@require_POST
def sheet_reversal_approve(request, pk):
    try:
        reversal = CollectionService(request).approve_reversal(reversal_id=pk)
    except CollectionSheet.DoesNotExist:
        from django.http import Http404

        raise Http404
    except PermissionDenied as error:
        return _json_error(str(error), {}, 403)
    except ValidationError as error:
        return _json_error("Collection reversal could not be approved.", _error_detail(error), 400)
    return _json_response(
        request,
        "Collection sheet and its postings were reversed.",
        data={"id": reversal.sheet_id, "status": reversal.sheet.status},
    ) or redirect(
        "collections:Module_Collections_sheet_detail", pk=reversal.sheet_id
    )


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
