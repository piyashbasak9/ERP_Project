from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from core.audit.services import log_action
from core.common.popup import popup_json_response, render_popup_form

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


@require_GET
def product_list(request):
    if "page" in request.GET or request.GET.get("format") == "json":
        products = LoanProduct.objects.all()
        status = request.GET.get("status", "").strip()
        if status in {"active", "inactive"}:
            products = products.filter(is_active=status == "active")
        query = request.GET.get("searchString", request.GET.get("q", "")).strip()
        if query:
            products = products.filter(
                Q(code__icontains=query) | Q(name__icontains=query)
            )
        order_fields = {
            "code": "code",
            "name": "name",
            "annual_interest_rate": "annual_interest_rate",
            "is_active": "is_active",
        }
        order = order_fields.get(request.GET.get("sidx", "code"), "code")
        if request.GET.get("sord", "asc").lower() == "desc":
            order = f"-{order}"
        page_obj = Paginator(products.order_by(order), 25).get_page(
            request.GET.get("page", 1)
        )
        return JsonResponse({
            "page": page_obj.number,
            "total": page_obj.paginator.num_pages,
            "records": page_obj.paginator.count,
            "rows": [
                {
                    "id": product.pk,
                    "code": product.code,
                    "name": product.name,
                    "method": product.get_interest_method_display(),
                    "rate": str(product.annual_interest_rate),
                    "amount": f"{product.min_amount:.2f} – {product.max_amount:.2f}",
                    "term": f"{product.min_term}–{product.max_term}",
                    "frequency": product.get_installment_frequency_display(),
                    "active": product.is_active,
                }
                for product in page_obj.object_list
            ],
        })
    return render(request, "loans/product_list.html")


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
    return render(request, "loans/application_list.html", {"applications": applications})


@require_GET
def disbursement_list(request):
    applications = LoanApplication.objects.filter(
        status=LoanApplication.STATUS_DISBURSED
    ).select_related("branch", "member", "product", "loan")
    return render(request, "loans/disbursement_list.html", {"applications": applications})


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
    return render(
        request,
        "loans/portfolio.html",
        {
            "result": result,
            "par": result["par"],
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
    ).order_by("-payment_date", "-pk")
    return render(request, "loans/repayment_list.html", {"payments": payments})


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
    tiers = LoanApprovalTier.objects.select_related("branch", "role").order_by(
        "branch_type", "branch__name", "role__name"
    )
    return render(request, "loans/approval_tiers.html", {"tiers": tiers})


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
    buckets = LoanPARBucket.objects.order_by("minimum_days")
    return render(request, "loans/par_buckets.html", {"buckets": buckets})


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
