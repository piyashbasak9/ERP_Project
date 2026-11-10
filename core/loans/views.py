from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.html import format_html, format_html_join
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from core.accounts.permission_utils import user_has_route_permission
from core.audit.services import log_action
from core.common.popup import popup_json_response, render_popup_form
from core.common.templatetags.user_formatting import config_money
from core.configuration.services import get_system_configuration

from .forms import (
    LoanApplicationForm,
    LoanApprovalTierForm,
    LoanDisbursementForm,
    LoanPARBucketForm,
    LoanProductForm,
    LoanRecoveryForm,
    LoanRepaymentForm,
    LoanRescheduleForm,
    LoanReviewForm,
    LoanSettlementForm,
    LoanWriteOffForm,
)
from .models import (
    Loan,
    LoanApplication,
    LoanApprovalTier,
    LoanInstallment,
    LoanPARBucket,
    LoanPayment,
    LoanPenalty,
    LoanProduct,
    LoanStatusHistory,
)
from .services import LoanService


def _form(request, form, title):
    return render_popup_form(
        request, "loans/form.html", {"form": form, "title": title}
    )


def _grid_page(request, queryset, order_fields, default_sort, default_order="asc"):
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


def _list_page_context(request, *, title, default_sort, default_order="asc",
                       add_route=None, add_title="", filters, columns):
    return {
        "list_title": title,
        "grid_url": request.path,
        "filter_layout": "members",
        "default_sort_name": default_sort,
        "default_sort_order": default_order,
        "initial_page_text": "Page 1 of 1",
        "list_actions": [],
        "add_url": (
            reverse(f"loans:{add_route}")
            if add_route and user_has_route_permission(request.user, add_route)
            else ""
        ),
        "add_title": add_title,
        "list_filters": filters,
        "list_columns": columns,
    }


@require_GET
def product_list(request):
    if request.GET.get("ajax") == "1" or request.GET.get("format") == "json":
        products = LoanProduct.objects.all()
        status = request.GET.get("status", "").strip()
        if status in {"active", "inactive"}:
            products = products.filter(is_active=status == "active")
        code = request.GET.get("code", "").strip()
        name = request.GET.get("name", "").strip()
        query = request.GET.get("searchString", request.GET.get("q", "")).strip()
        if code:
            products = products.filter(code__icontains=code)
        if name:
            products = products.filter(name__icontains=name)
        if query and not code and not name:
            products = products.filter(
                Q(code__icontains=query) | Q(name__icontains=query)
            )
        order_fields = {
            "code": "code",
            "name": "name",
            "method": "interest_method",
            "rate": "annual_interest_rate",
            "annual_interest_rate": "annual_interest_rate",
            "amount": "min_amount",
            "term": "min_term",
            "frequency": "installment_frequency",
            "status": "is_active",
            "is_active": "is_active",
        }
        order = order_fields.get(request.GET.get("sidx", "code"), "code")
        if request.GET.get("sord", "asc").lower() == "desc":
            order = f"-{order}"
        try:
            page_size = min(max(int(request.GET.get("rows", 20)), 1), 200)
        except (TypeError, ValueError):
            page_size = 20
        page_obj = Paginator(products.order_by(order, "pk"), page_size).get_page(
            request.GET.get("page", 1)
        )
        can_edit = user_has_route_permission(
            request.user, "Module_Loans_product_edit"
        )
        can_activate = user_has_route_permission(
            request.user, "Module_Loans_product_activate"
        )
        can_deactivate = user_has_route_permission(
            request.user, "Module_Loans_product_deactivate"
        )
        rows = []
        for product in page_obj.object_list:
            actions = []
            if can_edit:
                actions.append(format_html(
                    '<a class="btn btn-sm btn-outline-primary" href="{}?popup=1" '
                    'data-popup data-popup-title="Edit loan product">Edit</a>',
                    reverse("loans:Module_Loans_product_edit", args=[product.pk]),
                ))
            can_toggle = can_deactivate if product.is_active else can_activate
            if can_toggle:
                action = "deactivate" if product.is_active else "activate"
                label = "Deactivate" if product.is_active else "Activate"
                actions.append(format_html(
                    '<button class="btn btn-sm {}" type="button" data-toggle-product="{}">'
                    '{}</button>',
                    "btn-outline-danger" if product.is_active else "btn-outline-success",
                    reverse(f"loans:Module_Loans_product_{action}", args=[product.pk]),
                    label,
                ))
            rows.append({
                "id": product.pk,
                "code": product.code,
                "name": product.name,
                "method": product.get_interest_method_display(),
                "rate": str(product.annual_interest_rate),
                "amount": f"{product.min_amount:.2f} – {product.max_amount:.2f}",
                "term": f"{product.min_term}–{product.max_term}",
                "frequency": product.get_installment_frequency_display(),
                "status": "Active" if product.is_active else "Inactive",
                "active": product.is_active,
                "actions": format_html_join(
                    " ", "{}", ((action,) for action in actions)
                ),
            })
        return JsonResponse({
            "page": page_obj.number,
            "total": page_obj.paginator.num_pages,
            "records": page_obj.paginator.count,
            "rows": rows,
        })
    return render(request, "loans/product_list.html", {
        "list_title": "Loan products",
        "grid_url": request.path,
        "filter_layout": "members",
        "initial_page_text": "Page 1 of 1",
        "add_url": (
            reverse("loans:Module_Loans_product_add")
            if user_has_route_permission(request.user, "Module_Loans_product_add")
            else ""
        ),
        "add_title": "Create loan product",
        "list_filters": [
            {
                "name": "code", "label": "Product code",
                "value": request.GET.get("code", ""), "placeholder": "Code",
            },
            {
                "name": "name", "label": "Product name",
                "value": request.GET.get("name", ""), "placeholder": "Name",
            },
            {
                "name": "status", "label": "Status", "type": "select",
                "value": request.GET.get("status", ""),
                "options": (("active", "Active"), ("inactive", "Inactive")),
            },
        ],
        "list_columns": [
            {"name": "code", "label": "Code", "width": 100},
            {"name": "name", "label": "Name", "width": 190},
            {"name": "method", "label": "Method", "width": 130},
            {"name": "rate", "label": "Rate %", "width": 100, "align": "right"},
            {"name": "amount", "label": "Amount range", "width": 160},
            {"name": "term", "label": "Term range", "width": 100},
            {"name": "frequency", "label": "Frequency", "width": 120},
            {"name": "status", "label": "Status", "width": 100},
            {"name": "actions", "label": "Actions", "width": 180},
        ],
    })


@require_http_methods(["GET", "POST"])
def product_form(request, pk=None):
    instance = get_object_or_404(LoanProduct, pk=pk) if pk else None
    old_values = _product_values(instance) if instance else None
    form = LoanProductForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        product = form.save()
        log_action(
            "Update" if instance else "Create",
            "LoanProduct",
            product.pk,
            old_values=old_values,
            new_values=_product_values(product),
        )
        message = "Loan product saved."
        response = popup_json_response(
            request, message=message, data={"id": product.pk}
        )
        if response is not None:
            return response
        messages.success(request, message)
        return redirect("loans:Module_Loans_products")
    return _form(request, form, "Edit loan product" if instance else "Create loan product")


def _product_values(product):
    if product is None:
        return None
    values = {}
    for field in product._meta.concrete_fields:
        value = getattr(product, field.attname)
        values[field.name] = (
            str(value)
            if value is not None and field.get_internal_type() == "DecimalField"
            else value
        )
    return values


@require_POST
def product_activate(request, pk):
    return _set_product_active(request, pk, True)


@require_POST
def product_deactivate(request, pk):
    return _set_product_active(request, pk, False)


@transaction.atomic
def _set_product_active(request, pk, active):
    product = get_object_or_404(LoanProduct.objects.select_for_update(), pk=pk)
    old_values = _product_values(product)
    if product.is_active != active:
        product.is_active = active
        product.save(update_fields=["is_active"])
        log_action(
            "Activate" if active else "Deactivate",
            "LoanProduct",
            product.pk,
            old_values=old_values,
            new_values=_product_values(product),
        )
    message = "Loan product activated." if active else "Loan product deactivated."
    if request.headers.get("Accept") == "application/json":
        return JsonResponse({"success": True, "message": message, "data": {"id": product.pk}})
    messages.success(request, message)
    return redirect("loans:Module_Loans_products")

@require_GET
def application_list(request):
    applications = LoanApplication.objects.select_related(
        "branch", "member", "product", "created_by", "reviewed_by"
    )
    code = request.GET.get("code", "").strip()
    name = request.GET.get("name", "").strip()
    if code:
        applications = applications.filter(member__member_code__icontains=code)
    if name:
        applications = applications.filter(
            Q(member__first_name__icontains=name)
            | Q(member__last_name__icontains=name)
        )
    status = request.GET.get("status", "")
    if status in dict(LoanApplication.STATUS_CHOICES):
        applications = applications.filter(status=status)

    if request.GET.get("ajax") == "1":
        order_fields = {
            "member_code": "member__member_code",
            "full_name": "member__first_name",
            "branch": "branch__code",
            "product": "product__name",
            "requested_amount": "requested_amount",
            "approved_amount": "approved_amount",
            "term": "term",
            "cycle_number": "cycle_number",
            "status": "status",
            "maker_checker": "created_by__username",
            "created_at": "created_at",
        }
        order = order_fields.get(request.GET.get("sidx"), "created_at")
        if request.GET.get("sord", "desc").lower() != "asc":
            order = f"-{order}"
        try:
            page_size = min(max(int(request.GET.get("rows", 20)), 1), 200)
        except (TypeError, ValueError):
            page_size = 20
        page_obj = Paginator(
            applications.order_by(order, "pk"),
            page_size,
        ).get_page(request.GET.get("page", 1))

        permissions = {
            route: user_has_route_permission(request.user, route)
            for route in (
                "Module_Loans_application_submit",
                "Module_Loans_application_review",
                "Module_Loans_application_cancel",
                "Module_Loans_disbursement_add",
            )
        }
        csrf_token = get_token(request)
        rows = []
        for application in page_obj.object_list:
            actions = []
            if (
                application.status in {
                    LoanApplication.STATUS_DRAFT,
                    LoanApplication.STATUS_RETURNED,
                }
                and permissions["Module_Loans_application_submit"]
            ):
                actions.append(format_html(
                    '<form class="d-inline" method="post" action="{}">'
                    '<input type="hidden" name="csrfmiddlewaretoken" value="{}">'
                    '<button class="btn btn-sm btn-outline-primary" type="submit">Submit</button>'
                    '</form>',
                    reverse(
                        "loans:Module_Loans_application_submit",
                        args=[application.pk],
                    ),
                    csrf_token,
                ))
            if (
                application.status == LoanApplication.STATUS_SUBMITTED
                and permissions["Module_Loans_application_review"]
            ):
                actions.append(format_html(
                    '<a class="btn btn-sm btn-outline-primary" href="{}?popup=1" '
                    'data-popup data-popup-title="Review loan application">Review</a>',
                    reverse(
                        "loans:Module_Loans_application_review",
                        args=[application.pk],
                    ),
                ))
            if (
                application.status == LoanApplication.STATUS_APPROVED
                and permissions["Module_Loans_disbursement_add"]
            ):
                actions.append(format_html(
                    '<a class="btn btn-sm btn-outline-success" href="{}?popup=1" '
                    'data-popup data-popup-title="Disburse loan">Disburse</a>',
                    reverse(
                        "loans:Module_Loans_disbursement_add",
                        args=[application.pk],
                    ),
                ))
            if (
                application.status in {
                    LoanApplication.STATUS_DRAFT,
                    LoanApplication.STATUS_SUBMITTED,
                    LoanApplication.STATUS_APPROVED,
                }
                and permissions["Module_Loans_application_cancel"]
            ):
                actions.append(format_html(
                    '<form class="d-inline" method="post" action="{}">'
                    '<input type="hidden" name="csrfmiddlewaretoken" value="{}">'
                    '<button class="btn btn-sm btn-outline-danger" type="submit">Cancel</button>'
                    '</form>',
                    reverse(
                        "loans:Module_Loans_application_cancel",
                        args=[application.pk],
                    ),
                    csrf_token,
                ))
            rows.append({
                "id": application.pk,
                "member_code": application.member.member_code,
                "full_name": application.member.full_name,
                "branch": application.branch.code,
                "product": application.product.name,
                "requested_amount": str(application.requested_amount),
                "approved_amount": (
                    str(application.approved_amount)
                    if application.approved_amount is not None
                    else "—"
                ),
                "term": application.term,
                "cycle_number": application.cycle_number,
                "status": application.get_status_display(),
                "maker_checker": (
                    f"{application.created_by}"
                    + (
                        f" / {application.reviewed_by}"
                        if application.reviewed_by_id
                        else ""
                    )
                ),
                "created_at": timezone.localtime(application.created_at).strftime(
                    "%Y-%m-%d %H:%M"
                ),
                "actions": format_html_join(
                    " ", "{}", ((action,) for action in actions)
                ),
            })
        return JsonResponse({
            "rows": rows,
            "page": page_obj.number,
            "total": page_obj.paginator.num_pages,
            "records": page_obj.paginator.count,
        })

    return render(request, "loans/application_list.html", {
        "list_title": "Loan applications",
        "grid_url": request.path,
        "filter_layout": "members",
        "default_sort_name": "created_at",
        "default_sort_order": "desc",
        "initial_page_text": "Page 1 of 1",
        "add_url": (
            reverse("loans:Module_Loans_application_add")
            if user_has_route_permission(
                request.user, "Module_Loans_application_add"
            )
            else ""
        ),
        "add_title": "New loan application",
        "list_filters": [
            {
                "name": "code", "label": "Member code",
                "value": code, "placeholder": "Member code",
            },
            {
                "name": "name", "label": "Name",
                "value": name, "placeholder": "Member name",
            },
            {
                "name": "status", "label": "Status", "type": "select",
                "value": status, "options": LoanApplication.STATUS_CHOICES,
            },
        ],
        "list_columns": [
            {"name": "member_code", "label": "Member code", "width": 130},
            {"name": "full_name", "label": "Name", "width": 190},
            {"name": "branch", "label": "Branch", "width": 100},
            {"name": "product", "label": "Product", "width": 170},
            {"name": "requested_amount", "label": "Requested", "width": 120, "align": "right"},
            {"name": "approved_amount", "label": "Approved", "width": 120, "align": "right"},
            {"name": "term", "label": "Term", "width": 80},
            {"name": "cycle_number", "label": "Cycle", "width": 80},
            {"name": "status", "label": "Status", "width": 110},
            {"name": "maker_checker", "label": "Maker / checker", "width": 170},
            {"name": "created_at", "label": "Created at", "width": 150, "hidden": True},
            {"name": "actions", "label": "Actions", "width": 250},
        ],
    })


@require_GET
def disbursement_list(request):
    applications = LoanApplication.objects.filter(
        status=LoanApplication.STATUS_DISBURSED
    ).select_related("branch", "member", "product", "loan")
    code = request.GET.get("code", "").strip()
    name = request.GET.get("name", "").strip()
    branch = request.GET.get("branch", "").strip()
    product = request.GET.get("product", "").strip()
    date_from = request.GET.get("date_from", "").strip()
    date_to = request.GET.get("date_to", "").strip()
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
        return HttpResponseBadRequest("The start date must be on or before the end date.")
    if code:
        applications = applications.filter(member__member_code__icontains=code)
    if name:
        applications = applications.filter(
            Q(member__first_name__icontains=name)
            | Q(member__last_name__icontains=name)
        )
    if branch:
        applications = applications.filter(branch__code__icontains=branch)
    if product:
        applications = applications.filter(product__name__icontains=product)
    if parsed_date_from:
        applications = applications.filter(loan__disbursed_at__gte=parsed_date_from)
    if parsed_date_to:
        applications = applications.filter(loan__disbursed_at__lte=parsed_date_to)

    order_fields = {
        "member_code": "member__member_code",
        "full_name": "member__first_name",
        "branch": "branch__code",
        "product": "product__name",
        "principal": "loan__principal",
        "disbursed_at": "loan__disbursed_at",
        "voucher": "loan__journal_entry__voucher_number",
    }
    paginator, page_obj = _grid_page(
        request, applications, order_fields, "disbursed_at", "desc"
    )
    if request.GET.get("ajax") == "1":
        can_view_schedule = user_has_route_permission(
            request.user, "Module_Loans_schedule"
        )
        rows = []
        configuration = get_system_configuration()
        for application in page_obj.object_list:
            actions = []
            if can_view_schedule:
                actions.append(format_html(
                    '<a href="{}">Schedule</a>',
                    reverse(
                        "loans:Module_Loans_schedule",
                        args=[application.loan_id],
                    ),
                ))
            rows.append({
                "id": application.loan_id,
                "member_code": application.member.member_code,
                "full_name": application.member.full_name,
                "branch": application.branch.code,
                "product": application.product.name,
                "principal": config_money(
                    application.loan.principal, configuration
                ),
                "disbursed_at": application.loan.disbursed_at.isoformat(),
                "voucher": application.loan.journal_entry.voucher_number,
                "actions": format_html_join(
                    " | ", "{}", ((action,) for action in actions)
                ),
            })
        return JsonResponse({
            "rows": rows,
            "page": page_obj.number,
            "total": paginator.num_pages,
            "records": paginator.count,
        })

    context = _list_page_context(
        request,
        title="Loan disbursements",
        default_sort="disbursed_at",
        default_order="desc",
        filters=[
            {
                "name": "code", "label": "Member code",
                "value": code, "placeholder": "Member code",
            },
            {
                "name": "name", "label": "Member name",
                "value": name, "placeholder": "Member name",
            },
            {
                "name": "branch", "label": "Branch",
                "value": branch, "placeholder": "Branch code",
            },
            {
                "name": "product", "label": "Product",
                "value": product, "placeholder": "Product name",
            },
            {
                "name": "date", "label": "Disbursement date",
                "type": "date-range",
                "from_name": "date_from", "from_value": date_from,
                "to_name": "date_to", "to_value": date_to,
            },
        ],
        columns=[
            {"name": "member_code", "label": "Member code", "width": 135},
            {"name": "full_name", "label": "Member", "width": 180},
            {"name": "branch", "label": "Branch", "width": 100},
            {"name": "product", "label": "Product", "width": 180},
            {
                "name": "principal", "label": "Principal", "width": 140,
                "align": "right",
            },
            {"name": "disbursed_at", "label": "Date", "width": 120},
            {"name": "voucher", "label": "Ledger voucher", "width": 170},
            {"name": "actions", "label": "Actions", "width": 100},
        ],
    )
    context["initial_page_text"] = (
        f"Page {page_obj.number} of {paginator.num_pages}"
    )
    return render(request, "loans/disbursement_list.html", context)


@require_http_methods(["GET", "POST"])
def application_create(request):
    form = LoanApplicationForm(request.POST or None, request=request)
    if request.method == "POST" and form.is_valid():
        try:
            LoanService(request).create_application(
                branch_id=form.cleaned_data["branch"].pk,
                member_id=form.cleaned_data["member"].pk,
                product_id=form.cleaned_data["product"].pk,
                amount=form.cleaned_data["requested_amount"],
                term=form.cleaned_data["term"],
                purpose=form.cleaned_data["purpose"],
                idempotency_key=form.cleaned_data["idempotency_key"],
                guarantor_id=(
                    form.cleaned_data["guarantor"].pk
                    if form.cleaned_data["guarantor"]
                    else None
                ),
                collateral=(
                    {
                        "description": form.cleaned_data["collateral_description"],
                        "reference_number": form.cleaned_data["collateral_reference"],
                        "estimated_value": form.cleaned_data["collateral_value"],
                    }
                    if form.cleaned_data["collateral_description"]
                    else None
                ),
            )
        except ValidationError as error:
            form.add_error(None, error)
        else:
            response = popup_json_response(
                request,
                message="Loan application saved.",
            )
            if response is not None:
                return response
            messages.success(request, "Loan application saved.")
            return redirect("loans:Module_Loans_applications")
    return _form(request, form, "New loan application")


@require_POST
def application_submit(request, pk):
    try:
        LoanService(request).submit(application_id=pk)
    except LoanApplication.DoesNotExist:
        return render(request, "access_denied.html", status=404)
    except ValidationError as error:
        messages.error(request, "; ".join(error.messages))
    else:
        messages.success(request, "Application submitted for review.")
    return redirect("loans:Module_Loans_applications")


@require_http_methods(["GET", "POST"])
def application_review(request, pk):
    application = get_object_or_404(LoanApplication.objects, pk=pk)
    form = LoanReviewForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            LoanService(request).review(
                application_id=pk,
                decision=form.cleaned_data["decision"],
                comment=form.cleaned_data["comment"],
                approved_amount=form.cleaned_data["approved_amount"],
            )
        except ValidationError as error:
            form.add_error(None, error)
        else:
            response = popup_json_response(
                request,
                message="Loan application reviewed.",
                data={"id": application.pk},
            )
            if response is not None:
                return response
            messages.success(request, "Loan application reviewed.")
            return redirect("loans:Module_Loans_applications")
    return _form(request, form, f"Review application {application.pk}")


@require_http_methods(["GET", "POST"])
def disbursement_form(request, pk):
    application = get_object_or_404(LoanApplication.objects, pk=pk)
    form = LoanDisbursementForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            LoanService(request).disburse(
                application_id=pk,
                disbursement_date=form.cleaned_data["disbursement_date"],
                channel=form.cleaned_data["channel"],
                idempotency_key=form.cleaned_data["idempotency_key"],
            )
        except ValidationError as error:
            form.add_error(None, error)
        else:
            response = popup_json_response(
                request,
                message="Loan disbursed and posted to the ledger.",
                data={"id": application.pk},
            )
            if response is not None:
                return response
            messages.success(request, "Loan disbursed and posted to the ledger.")
            return redirect("loans:Module_Loans_portfolio")
    return _form(request, form, f"Disburse application {application.pk}")


@require_GET
def portfolio(request):
    result = LoanService(request).portfolio(
        as_of_date=timezone.localdate(),
        branch_ids=request.user.accessible_branch_ids(request.active_branch_id),
    )
    loans = result["loans"].select_related("branch", "member", "product")
    code = request.GET.get("code", "").strip()
    name = request.GET.get("name", "").strip()
    branch = request.GET.get("branch", "").strip()
    product = request.GET.get("product", "").strip()
    if code:
        loans = loans.filter(member__member_code__icontains=code)
    if name:
        loans = loans.filter(
            Q(member__first_name__icontains=name)
            | Q(member__last_name__icontains=name)
        )
    if branch:
        loans = loans.filter(branch__code__icontains=branch)
    if product:
        loans = loans.filter(product__name__icontains=product)
    order_fields = {
        "loan": "pk",
        "member_code": "member__member_code",
        "branch": "branch__code",
        "product": "product__name",
        "principal": "principal",
        "outstanding": "outstanding_principal",
        "status": "status",
    }
    paginator, page_obj = _grid_page(
        request, loans, order_fields, "loan", "desc"
    )
    if request.GET.get("ajax") == "1":
        configuration = get_system_configuration()
        action_routes = [
            ("Module_Loans_statement", "Statement"),
            ("Module_Loans_history", "History"),
            ("Module_Loans_repayment_add", "Repay"),
            ("Module_Loans_reschedule", "Reschedule"),
            ("Module_Loans_settle", "Settle"),
            ("Module_Loans_write_off", "Write off"),
        ]
        allowed_actions = [
            (route, label)
            for route, label in action_routes
            if user_has_route_permission(request.user, route)
        ]
        rows = []
        for loan in page_obj.object_list:
            actions = []
            for route, label in allowed_actions:
                actions.append(format_html(
                    '<a href="{}"{}>{}</a>',
                    reverse(f"loans:{route}", args=[loan.pk])
                    + (
                        "?popup=1"
                        if route
                        in {
                            "Module_Loans_repayment_add",
                            "Module_Loans_reschedule",
                            "Module_Loans_settle",
                            "Module_Loans_write_off",
                        }
                        else ""
                    ),
                    (
                        format_html(
                            ' data-popup data-popup-title="{}"',
                            label,
                        )
                        if route
                        in {
                            "Module_Loans_repayment_add",
                            "Module_Loans_reschedule",
                            "Module_Loans_settle",
                            "Module_Loans_write_off",
                        }
                        else ""
                    ),
                    label,
                ))
            rows.append({
                "loan": loan.pk,
                "member_code": loan.member.member_code,
                "branch": loan.branch.code,
                "product": loan.product.name,
                "principal": config_money(loan.principal, configuration),
                "outstanding": config_money(
                    loan.outstanding_principal, configuration
                ),
                "status": loan.get_status_display(),
                "actions": format_html_join(
                    " | ", "{}", ((action,) for action in actions)
                ),
            })
        return JsonResponse({
            "rows": rows,
            "page": page_obj.number,
            "total": paginator.num_pages,
            "records": paginator.count,
        })

    return render(
        request,
        "loans/portfolio.html",
        {
            "result": result,
            "par": result["par"],
            "initial_page_text": (
                f"Page {page_obj.number} of {paginator.num_pages}"
            ),
            "can_record_recovery": user_has_route_permission(
                request.user, "Module_Loans_recovery"
            ),
            "grid_url": request.path,
            "list_title": "Loan portfolio",
            "filter_layout": "members",
            "default_sort_name": "loan",
            "default_sort_order": "desc",
            "list_actions": [],
            "add_url": "",
            "list_filters": [
                {
                    "name": "code", "label": "Member code",
                    "value": code, "placeholder": "Member code",
                },
                {
                    "name": "name", "label": "Member name",
                    "value": name, "placeholder": "Member name",
                },
                {
                    "name": "branch", "label": "Branch",
                    "value": branch, "placeholder": "Branch code",
                },
                {
                    "name": "product", "label": "Product",
                    "value": product, "placeholder": "Product name",
                },
            ],
            "list_columns": [
                {"name": "loan", "label": "Loan", "width": 90},
                {"name": "member_code", "label": "Member code", "width": 140},
                {"name": "branch", "label": "Branch", "width": 100},
                {"name": "product", "label": "Product", "width": 180},
                {
                    "name": "principal", "label": "Principal", "width": 140,
                    "align": "right",
                },
                {
                    "name": "outstanding", "label": "Outstanding",
                    "width": 140, "align": "right",
                },
                {"name": "status", "label": "Status", "width": 110},
                {"name": "actions", "label": "Actions", "width": 300},
            ],
            "written_off_loans": Loan.objects.filter(
                branch_id__in=request.user.accessible_branch_ids(
                    request.active_branch_id
                ),
                status=Loan.STATUS_WRITTEN_OFF,
            ).select_related("member", "branch", "product"),
        },
    )


@require_GET
def repayment_list(request):
    payments = LoanPayment.objects.select_related(
        "branch", "loan", "loan__member", "journal_entry", "created_by"
    )
    code = request.GET.get("code", "").strip()
    loan_id = request.GET.get("loan", "").strip()
    branch = request.GET.get("branch", "").strip()
    date_from = request.GET.get("date_from", "").strip()
    date_to = request.GET.get("date_to", "").strip()
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
        return HttpResponseBadRequest("The start date must be on or before the end date.")
    if code:
        payments = payments.filter(loan__member__member_code__icontains=code)
    if loan_id:
        if not loan_id.isdecimal():
            return HttpResponseBadRequest("Loan ID must be a whole number.")
        payments = payments.filter(loan_id=int(loan_id))
    if branch:
        payments = payments.filter(branch__code__icontains=branch)
    if parsed_date_from:
        payments = payments.filter(payment_date__gte=parsed_date_from)
    if parsed_date_to:
        payments = payments.filter(payment_date__lte=parsed_date_to)
    order_fields = {
        "payment_date": "payment_date",
        "loan": "loan_id",
        "member_code": "loan__member__member_code",
        "branch": "branch__code",
        "amount": "amount",
        "principal": "principal_paid",
        "interest": "interest_paid",
        "fees": "fee_paid",
        "penalty": "penalty_paid",
        "voucher": "journal_entry__voucher_number",
    }
    paginator, page_obj = _grid_page(
        request, payments, order_fields, "payment_date", "desc"
    )
    if request.GET.get("ajax") == "1":
        configuration = get_system_configuration()
        rows = [
            {
                "payment_date": payment.payment_date.isoformat(),
                "loan": payment.loan_id,
                "member_code": payment.loan.member.member_code,
                "branch": payment.branch.code,
                "amount": config_money(payment.amount, configuration),
                "principal": config_money(
                    payment.principal_paid, configuration
                ),
                "interest": config_money(payment.interest_paid, configuration),
                "fees": config_money(payment.fee_paid, configuration),
                "penalty": config_money(payment.penalty_paid, configuration),
                "voucher": payment.journal_entry.voucher_number,
            }
            for payment in page_obj.object_list
        ]
        return JsonResponse({
            "rows": rows,
            "page": page_obj.number,
            "total": paginator.num_pages,
            "records": paginator.count,
        })
    context = _list_page_context(
        request,
        title="Loan repayments",
        default_sort="payment_date",
        default_order="desc",
        filters=[
            {
                "name": "code", "label": "Member code",
                "value": code, "placeholder": "Member code",
            },
            {
                "name": "loan", "label": "Loan ID",
                "value": loan_id, "placeholder": "Loan ID",
            },
            {
                "name": "branch", "label": "Branch",
                "value": branch, "placeholder": "Branch code",
            },
            {
                "name": "date", "label": "Payment date",
                "type": "date-range",
                "from_name": "date_from", "from_value": date_from,
                "to_name": "date_to", "to_value": date_to,
            },
        ],
        columns=[
            {"name": "payment_date", "label": "Date", "width": 120},
            {"name": "loan", "label": "Loan", "width": 90},
            {"name": "member_code", "label": "Member code", "width": 140},
            {"name": "branch", "label": "Branch", "width": 100},
            {
                "name": "amount", "label": "Amount", "width": 140,
                "align": "right",
            },
            {
                "name": "principal", "label": "Principal", "width": 140,
                "align": "right",
            },
            {
                "name": "interest", "label": "Interest", "width": 140,
                "align": "right",
            },
            {"name": "fees", "label": "Fees", "width": 120, "align": "right"},
            {
                "name": "penalty", "label": "Penalty", "width": 120,
                "align": "right",
            },
            {"name": "voucher", "label": "Voucher", "width": 170},
        ],
    )
    context["initial_page_text"] = (
        f"Page {page_obj.number} of {paginator.num_pages}"
    )
    return render(request, "loans/repayment_list.html", context)


@require_http_methods(["GET", "POST"])
def repayment_form(request, pk):
    loan = get_object_or_404(Loan.objects.select_related("member"), pk=pk)
    form = LoanRepaymentForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            LoanService(request).repay(
                loan_id=loan.pk,
                amount=form.cleaned_data["amount"],
                payment_date=form.cleaned_data["payment_date"],
                payment_channel=form.cleaned_data["payment_channel"],
                idempotency_key=form.cleaned_data["idempotency_key"],
            )
        except ValidationError as error:
            form.add_error(None, error)
        else:
            response = popup_json_response(
                request,
                message="Repayment posted to the ledger.",
                data={"id": loan.pk},
            )
            if response is not None:
                return response
            messages.success(request, "Repayment posted to the ledger.")
            return redirect("loans:Module_Loans_portfolio")
    return _form(request, form, f"Repay loan {loan.pk}")


@require_http_methods(["GET", "POST"])
def reschedule_form(request, pk):
    loan = get_object_or_404(Loan.objects, pk=pk)
    form = LoanRescheduleForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            LoanService(request).reschedule(
                loan_id=loan.pk,
                new_term=form.cleaned_data["new_term"],
                effective_date=form.cleaned_data["effective_date"],
                reason=form.cleaned_data["reason"],
                idempotency_key=form.cleaned_data["idempotency_key"],
            )
        except ValidationError as error:
            form.add_error(None, error)
        else:
            response = popup_json_response(
                request,
                message="A new schedule version was created.",
                data={"id": loan.pk},
            )
            if response is not None:
                return response
            messages.success(request, "A new schedule version was created.")
            return redirect("loans:Module_Loans_portfolio")
    return _form(request, form, f"Reschedule loan {loan.pk}")


@require_http_methods(["GET", "POST"])
def settlement_form(request, pk):
    loan = get_object_or_404(Loan.objects, pk=pk)
    form = LoanSettlementForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            LoanService(request).settle(
                loan_id=loan.pk,
                settlement_date=form.cleaned_data["settlement_date"],
                idempotency_key=form.cleaned_data["idempotency_key"],
                reason=form.cleaned_data["reason"],
            )
        except ValidationError as error:
            form.add_error(None, error)
        else:
            response = popup_json_response(
                request,
                message="Loan settled.",
                data={"id": loan.pk},
            )
            if response is not None:
                return response
            messages.success(request, "Loan settled.")
            return redirect("loans:Module_Loans_portfolio")
    return _form(request, form, f"Settle loan {loan.pk}")


@require_http_methods(["GET", "POST"])
def write_off_form(request, pk):
    loan = get_object_or_404(Loan.objects, pk=pk)
    form = LoanWriteOffForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            LoanService(request).write_off(
                loan_id=loan.pk,
                write_off_date=form.cleaned_data["write_off_date"],
                reason=form.cleaned_data["reason"],
                idempotency_key=form.cleaned_data["idempotency_key"],
            )
        except ValidationError as error:
            form.add_error(None, error)
        else:
            response = popup_json_response(
                request,
                message="Loan written off and ledger entry posted.",
                data={"id": loan.pk},
            )
            if response is not None:
                return response
            messages.success(request, "Loan written off and ledger entry posted.")
            return redirect("loans:Module_Loans_portfolio")
    return _form(request, form, f"Write off loan {loan.pk}")


@require_http_methods(["GET", "POST"])
def recovery_form(request, pk):
    loan = get_object_or_404(
        Loan.objects, pk=pk, status=Loan.STATUS_WRITTEN_OFF
    )
    form = LoanRecoveryForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            LoanService(request).recover(
                loan_id=loan.pk,
                amount=form.cleaned_data["amount"],
                payment_date=form.cleaned_data["payment_date"],
                payment_channel=form.cleaned_data["payment_channel"],
                idempotency_key=form.cleaned_data["idempotency_key"],
            )
        except ValidationError as error:
            form.add_error(None, error)
        else:
            response = popup_json_response(
                request,
                message="Recovery posted to the ledger.",
                data={"id": loan.pk},
            )
            if response is not None:
                return response
            messages.success(request, "Recovery posted to the ledger.")
            return redirect("loans:Module_Loans_portfolio")
    return _form(request, form, f"Recover written-off loan {loan.pk}")


@require_GET
def schedule(request, pk):
    loan = get_object_or_404(Loan.objects, pk=pk)
    installments = LoanInstallment.objects.filter(
        loan=loan, schedule_version=loan.schedule_version
    ).order_by("number")
    return render(
        request,
        "loans/schedule.html",
        {"loan": loan, "installments": installments},
    )


def _loan_statement_context(loan):
    installments = LoanInstallment.objects.filter(loan=loan).order_by(
        "schedule_version", "number"
    )
    payments = LoanPayment.objects.filter(loan=loan).select_related(
        "created_by", "journal_entry"
    )
    penalties = LoanPenalty.objects.filter(
        installment__loan=loan
    ).select_related("installment").order_by("as_of_date", "pk")
    history = list(loan.application.status_history.select_related("changed_by"))
    history.extend(loan.status_history.select_related("changed_by"))
    history.sort(key=lambda item: (item.changed_at, item.pk))
    outstanding_interest = sum(
        (
            row.interest_remaining
            for row in installments
            if row.schedule_version == loan.schedule_version
        ),
        0,
    )
    outstanding_fees = sum(
        (
            row.fee_remaining
            for row in installments
            if row.schedule_version == loan.schedule_version
        ),
        0,
    )
    penalty_balance = sum((item.amount - item.paid for item in penalties), 0)
    today = timezone.localdate()
    overdue_installment = next(
        (
            row
            for row in installments
            if row.schedule_version == loan.schedule_version
            and row.due_date < today
            and (
                row.principal_remaining > 0
                or row.interest_remaining > 0
                or row.fee_remaining > 0
            )
        ),
        None,
    )
    days_past_due = (
        (today - overdue_installment.due_date).days if overdue_installment else 0
    )
    bucket = LoanPARBucket.objects.filter(
        is_active=True,
        minimum_days__lte=days_past_due,
    ).filter(
        Q(maximum_days__isnull=True) | Q(maximum_days__gte=days_past_due)
    ).first()
    return {
        "loan": loan,
        "installments": installments,
        "payments": payments,
        "penalties": penalties,
        "status_history": history,
        "outstanding_interest": outstanding_interest,
        "outstanding_fees": outstanding_fees,
        "penalty_balance": penalty_balance,
        "outstanding_total": (
            loan.outstanding_principal
            + outstanding_interest
            + outstanding_fees
            + penalty_balance
        ),
        "product_name": loan.product_term("name"),
        "days_past_due": days_past_due,
        "par_classification": bucket.name if bucket else "Unclassified",
    }


@require_GET
def loan_statement(request, pk):
    loan = get_object_or_404(
        Loan.objects.select_related("member", "branch", "product", "application"),
        pk=pk,
    )
    return render(
        request,
        "loans/statement.html",
        _loan_statement_context(loan),
    )


@require_GET
def loan_history(request, pk):
    loan = get_object_or_404(
        Loan.objects.select_related("member", "branch", "product", "application"),
        pk=pk,
    )
    context = _loan_statement_context(loan)
    return render(request, "loans/history.html", context)


@require_GET
def approval_tier_list(request):
    tiers = LoanApprovalTier.objects.select_related("branch", "role")
    branch_type = request.GET.get("branch_type", "").strip()
    scope = request.GET.get("scope", "").strip()
    role = request.GET.get("role", "").strip()
    active = request.GET.get("active", "").strip()
    if branch_type in dict(LoanApprovalTier._meta.get_field("branch_type").choices):
        tiers = tiers.filter(branch_type=branch_type)
    if scope:
        tiers = tiers.filter(
            Q(branch__name__icontains=scope)
            | Q(branch__isnull=True, branch_type__icontains=scope)
        )
    if role:
        tiers = tiers.filter(role__name__icontains=role)
    if active in {"true", "false"}:
        tiers = tiers.filter(is_active=(active == "true"))
    order_fields = {
        "level": "branch_type",
        "scope": "branch__name",
        "role": "role__name",
        "limit": "amount_limit",
        "status": "is_active",
    }
    paginator, page_obj = _grid_page(
        request, tiers, order_fields, "level"
    )
    if request.GET.get("ajax") == "1":
        configuration = get_system_configuration()
        can_edit = user_has_route_permission(
            request.user, "Module_Loans_approval_tier_edit"
        )
        rows = []
        for tier in page_obj.object_list:
            scope_label = (
                tier.branch.name if tier.branch else "All branches at level"
            )
            edit = (
                format_html(
                    '<a href="{}?popup=1" data-popup data-popup-title="Edit approval tier">Edit</a>',
                    reverse(
                        "loans:Module_Loans_approval_tier_edit",
                        args=[tier.pk],
                    ),
                )
                if can_edit
                else ""
            )
            rows.append({
                "level": tier.get_branch_type_display(),
                "scope": scope_label,
                "role": tier.role.name,
                "limit": config_money(tier.amount_limit, configuration),
                "status": "Active" if tier.is_active else "Inactive",
                "actions": edit,
            })
        return JsonResponse({
            "rows": rows,
            "page": page_obj.number,
            "total": paginator.num_pages,
            "records": paginator.count,
        })
    context = _list_page_context(
        request,
        title="Approval tiers",
        default_sort="level",
        add_route="Module_Loans_approval_tier_add",
        add_title="Add approval tier",
        filters=[
            {
                "name": "branch_type", "label": "Level", "type": "select",
                "value": branch_type,
                "options": LoanApprovalTier._meta.get_field(
                    "branch_type"
                ).choices,
            },
            {
                "name": "scope", "label": "Branch scope",
                "value": scope, "placeholder": "Branch name or level",
            },
            {
                "name": "role", "label": "Role",
                "value": role, "placeholder": "Role name",
            },
            {
                "name": "active", "label": "Status", "type": "select",
                "value": active,
                "options": (("true", "Active"), ("false", "Inactive")),
            },
        ],
        columns=[
            {"name": "level", "label": "Level", "width": 130},
            {"name": "scope", "label": "Branch scope", "width": 200},
            {"name": "role", "label": "Role", "width": 160},
            {
                "name": "limit", "label": "Limit", "width": 150,
                "align": "right",
            },
            {"name": "status", "label": "Status", "width": 110},
            {"name": "actions", "label": "Actions", "width": 90},
        ],
    )
    context["initial_page_text"] = (
        f"Page {page_obj.number} of {paginator.num_pages}"
    )
    context["description"] = (
        "When a tier is configured for a branch level, a reviewer needs a "
        "matching role and a sufficient limit. A branch-specific tier takes "
        "precedence over a level-wide tier."
    )
    return render(request, "loans/approval_tiers.html", context)


@require_http_methods(["GET", "POST"])
def approval_tier_form(request, pk=None):
    instance = get_object_or_404(LoanApprovalTier, pk=pk) if pk else None
    old_values = (
        {
            "branch_type": instance.branch_type,
            "branch_id": instance.branch_id,
            "role_id": instance.role_id,
            "amount_limit": str(instance.amount_limit),
            "is_active": instance.is_active,
        }
        if instance
        else None
    )
    form = LoanApprovalTierForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        tier = form.save()
        log_action(
            "Update" if instance else "Create",
            "LoanApprovalTier",
            tier.pk,
            old_values=old_values,
            new_values={
                "branch_type": tier.branch_type,
                "branch_id": tier.branch_id,
                "role_id": tier.role_id,
                "amount_limit": str(tier.amount_limit),
                "is_active": tier.is_active,
            },
        )
        response = popup_json_response(
            request, message="Approval tier saved.", data={"id": tier.pk}
        )
        if response is not None:
            return response
        messages.success(request, "Approval tier saved.")
        return redirect("loans:Module_Loans_approval_tiers")
    return _form(
        request,
        form,
        "Edit approval tier" if instance else "Create approval tier",
    )


@require_GET
def par_bucket_list(request):
    buckets = LoanPARBucket.objects.all()
    name = request.GET.get("name", "").strip()
    active = request.GET.get("active", "").strip()
    if name:
        buckets = buckets.filter(name__icontains=name)
    if active in {"true", "false"}:
        buckets = buckets.filter(is_active=(active == "true"))
    order_fields = {
        "name": "name",
        "minimum_days": "minimum_days",
        "maximum_days": "maximum_days",
        "provision_rate": "provision_rate",
        "status": "is_active",
    }
    paginator, page_obj = _grid_page(
        request, buckets, order_fields, "minimum_days"
    )
    if request.GET.get("ajax") == "1":
        can_edit = user_has_route_permission(
            request.user, "Module_Loans_par_bucket_edit"
        )
        rows = []
        for bucket in page_obj.object_list:
            maximum_days = (
                str(bucket.maximum_days)
                if bucket.maximum_days is not None
                else "and above"
            )
            edit = (
                format_html(
                    '<a href="{}?popup=1" data-popup data-popup-title="Edit PAR bucket">Edit</a>',
                    reverse(
                        "loans:Module_Loans_par_bucket_edit",
                        args=[bucket.pk],
                    ),
                )
                if can_edit
                else ""
            )
            rows.append({
                "name": bucket.name,
                "days": f"{bucket.minimum_days}–{maximum_days}",
                "provision_rate": f"{bucket.provision_rate:.2f}%",
                "status": "Active" if bucket.is_active else "Inactive",
                "actions": edit,
            })
        return JsonResponse({
            "rows": rows,
            "page": page_obj.number,
            "total": paginator.num_pages,
            "records": paginator.count,
        })
    context = _list_page_context(
        request,
        title="PAR classification buckets",
        default_sort="minimum_days",
        add_route="Module_Loans_par_bucket_add",
        add_title="Add PAR bucket",
        filters=[
            {
                "name": "name", "label": "Class name",
                "value": name, "placeholder": "Bucket name",
            },
            {
                "name": "active", "label": "Status", "type": "select",
                "value": active,
                "options": (("true", "Active"), ("false", "Inactive")),
            },
        ],
        columns=[
            {"name": "name", "label": "Class", "width": 180},
            {"name": "days", "label": "Days overdue", "width": 180},
            {
                "name": "provision_rate", "label": "Provision rate",
                "width": 150, "align": "right",
            },
            {"name": "status", "label": "Status", "width": 110},
            {"name": "actions", "label": "Actions", "width": 90},
        ],
    )
    context["initial_page_text"] = (
        f"Page {page_obj.number} of {paginator.num_pages}"
    )
    return render(request, "loans/par_buckets.html", context)


@require_http_methods(["GET", "POST"])
def par_bucket_form(request, pk=None):
    instance = get_object_or_404(LoanPARBucket, pk=pk) if pk else None
    old_values = (
        {
            "name": instance.name,
            "minimum_days": instance.minimum_days,
            "maximum_days": instance.maximum_days,
            "provision_rate": str(instance.provision_rate),
            "is_active": instance.is_active,
        }
        if instance
        else None
    )
    form = LoanPARBucketForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        bucket = form.save()
        log_action(
            "Update" if instance else "Create",
            "LoanPARBucket",
            bucket.pk,
            old_values=old_values,
            new_values={
                "name": bucket.name,
                "minimum_days": bucket.minimum_days,
                "maximum_days": bucket.maximum_days,
                "provision_rate": str(bucket.provision_rate),
                "is_active": bucket.is_active,
            },
        )
        response = popup_json_response(
            request, message="PAR classification bucket saved.", data={"id": bucket.pk}
        )
        if response is not None:
            return response
        messages.success(request, "PAR classification bucket saved.")
        return redirect("loans:Module_Loans_par_buckets")
    return _form(
        request,
        form,
        "Edit PAR bucket" if instance else "Create PAR bucket",
    )


@require_GET
def classification_report(request):
    result = LoanService(request).classification_report(
        as_of_date=timezone.localdate(),
        branch_ids=request.user.accessible_branch_ids(request.active_branch_id),
    )
    return render(request, "loans/classification.html", result)


@require_GET
def classification_export_excel(request):
    result = LoanService(request).classification_report(
        as_of_date=timezone.localdate(),
        branch_ids=request.user.accessible_branch_ids(request.active_branch_id),
    )
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Loan classification"
    sheet.append(["Class", "Days past due", "Outstanding principal", "Provision rate %", "Provision"])
    for row in result["buckets"]:
        sheet.append([
            row["name"],
            f'{row["minimum_days"]}-{row["maximum_days"] or "and above"}',
            float(row["principal"]),
            float(row["provision_rate"]),
            float(row["provision"]),
        ])
    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = 'attachment; filename="loan-classification.xlsx"'
    workbook.save(response)
    return response


@require_GET
def classification_export_pdf(request):
    result = LoanService(request).classification_report(
        as_of_date=timezone.localdate(),
        branch_ids=request.user.accessible_branch_ids(request.active_branch_id),
    )
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import landscape, letter
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="loan-classification.pdf"'
    document = SimpleDocTemplate(response, pagesize=landscape(letter))
    rows = [["Class", "Days past due", "Outstanding principal", "Provision rate %", "Provision"]]
    rows.extend([
        [
            row["name"],
            f'{row["minimum_days"]}-{row["maximum_days"] or "and above"}',
            f'{row["principal"]:.2f}',
            f'{row["provision_rate"]:.2f}',
            f'{row["provision"]:.2f}',
        ]
        for row in result["buckets"]
    ])
    table = Table(rows, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#15375b")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
    ]))
    document.build([table])
    return response


@require_POST
@transaction.atomic
def cancel_application(request, pk):
    application = get_object_or_404(
        LoanApplication.objects.select_for_update(), pk=pk
    )
    if application.status not in {
        LoanApplication.STATUS_DRAFT,
        LoanApplication.STATUS_SUBMITTED,
        LoanApplication.STATUS_APPROVED,
    }:
        messages.error(request, "This application cannot be cancelled.")
        return redirect("loans:Module_Loans_applications")
    old_status = application.status
    application.status = LoanApplication.STATUS_CANCELLED
    application.save(update_fields=["status", "updated_at"])
    LoanStatusHistory.objects.create(
        application=application,
        old_status=old_status,
        new_status=application.status,
        changed_by=request.user,
    )
    log_action(
        "Cancel",
        "LoanApplication",
        application.pk,
        old_values={"status": old_status},
        new_values={"status": application.status},
        branch_id=application.branch_id,
    )
    messages.success(request, "Application cancelled.")
    return redirect("loans:Module_Loans_applications")
