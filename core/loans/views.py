from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from core.audit.services import log_action

from .forms import (
    LoanApplicationForm,
    LoanDisbursementForm,
    LoanProductForm,
    LoanRecoveryForm,
    LoanRepaymentForm,
    LoanRescheduleForm,
    LoanReviewForm,
    LoanSettlementForm,
    LoanWriteOffForm,
)
from .models import Loan, LoanApplication, LoanInstallment, LoanPayment, LoanProduct
from .services import LoanService


def _form(request, form, title):
    return render(request, "loans/form.html", {"form": form, "title": title})


@require_GET
def product_list(request):
    return render(
        request,
        "loans/product_list.html",
        {"products": LoanProduct.objects.order_by("code")},
    )


@require_http_methods(["GET", "POST"])
def product_form(request, pk=None):
    instance = get_object_or_404(LoanProduct, pk=pk) if pk else None
    form = LoanProductForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        product = form.save()
        log_action(
            "Update" if instance else "Create",
            "LoanProduct",
            product.pk,
            new_values={"code": product.code, "name": product.name},
        )
        messages.success(request, "Loan product saved.")
        return redirect("loans:Module_Loans_products")
    return _form(request, form, "Edit loan product" if instance else "Create loan product")


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
            )
        except ValidationError as error:
            form.add_error(None, error)
        else:
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
            )
        except ValidationError as error:
            form.add_error(None, error)
        else:
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
