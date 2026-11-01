import hashlib
import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import IntegrityError, transaction
from django.utils import timezone
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from core.accounting.models import Account, SystemAccountMapping
from core.accounting.services import JournalService
from core.audit.services import log_action
from core.branch.models import Member
from core.loans.models import (
    Loan,
    LoanApplication,
    LoanInstallment,
    LoanPenalty,
    LoanProduct,
    LoanStatusHistory,
)
from core.loans.services import generate_schedule
from core.savings.models import SavingsAccount, SavingsTransaction
from core.savings.services import SavingsService

from .models import ImportBatch
from .security import MAX_FILE_BYTES, safe_report_cell, validate_xlsx_archive

ROW_LIMIT = 5000
HEADERS = {
    ImportBatch.TYPE_MEMBERS: (
        "member_code",
        "first_name",
        "last_name",
        "phone",
        "email",
        "date_of_birth",
        "admission_date",
    ),
    ImportBatch.TYPE_SAVINGS_OPENING: (
        "account_number",
        "amount",
        "transaction_date",
    ),
    ImportBatch.TYPE_GL_OPENING: (
        "account_code",
        "debit",
        "credit",
        "journal_date",
        "narration",
    ),
    ImportBatch.TYPE_LOAN_OPENING: (
        "member_code",
        "product_code",
        "disbursed_amount",
        "disbursed_date",
        "term",
        "frequency",
        "outstanding_principal",
        "accrued_unpaid_interest",
        "overdue_installments",
        "unpaid_penalties",
        "last_payment_date",
        "opening_date",
        "next_due_date",
    ),
}


def upload_batch(*, uploaded_file, branch, import_type, user):
    if import_type not in HEADERS:
        raise ValidationError("Select a supported import type.")
    content = uploaded_file.read(MAX_FILE_BYTES + 1)
    validate_xlsx_archive(content, uploaded_file.name)
    digest = hashlib.sha256(content).hexdigest()
    existing = ImportBatch.objects.filter(file_hash=digest).first()
    if existing:
        if existing.branch_id != branch.pk or existing.import_type != import_type:
            raise ValidationError("This file was already submitted for a different import.")
        return existing, False
    try:
        with transaction.atomic():
            batch = ImportBatch.objects.create(
                branch=branch,
                created_by=user,
                import_type=import_type,
                file_hash=digest,
                source_name=uploaded_file.name[:255],
                source_file=ContentFile(content, name="upload.xlsx"),
            )
    except IntegrityError:
        existing = ImportBatch.objects.filter(file_hash=digest).first()
        if existing is None:
            raise
        if existing.branch_id != branch.pk or existing.import_type != import_type:
            raise ValidationError("This file was already submitted for a different import.")
        return existing, False
    log_action(
        "Create",
        "ImportBatch",
        batch.pk,
        new_values={
            "import_type": import_type,
            "file_hash": digest,
            "status": batch.status,
        },
        branch_id=branch.pk,
    )
    return batch, True


def _read_rows(batch):
    with batch.source_file.open("rb") as source:
        content = source.read()
    validate_xlsx_archive(content, batch.source_name)
    try:
        workbook = load_workbook(
            BytesIO(content),
            read_only=True,
            data_only=True,
            keep_links=False,
        )
    except (InvalidFileException, KeyError, ValueError) as exc:
        raise ValidationError("The uploaded workbook could not be read.") from exc
    worksheet = workbook.active
    rows = worksheet.iter_rows(values_only=True)
    header_row = next(rows, None)
    expected_headers = HEADERS[batch.import_type]
    normalized_headers = tuple(
        str(value).strip().lower() if value is not None else ""
        for value in (header_row or ())
    )
    if normalized_headers != expected_headers:
        workbook.close()
        raise ValidationError(
            "Workbook columns do not match the downloadable template."
        )
    result = []
    for row_number, values in enumerate(rows, start=2):
        if row_number > ROW_LIMIT + 1:
            workbook.close()
            raise ValidationError(f"Workbook exceeds the {ROW_LIMIT} row limit.")
        if not any(value is not None for value in values):
            continue
        result.append((row_number, dict(zip(expected_headers, values, strict=False))))
    workbook.close()
    return result


def _as_date(value, field):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError as exc:
            raise ValueError(f"{field} must be an ISO date.") from exc
    raise ValueError(f"{field} is required and must be a date.")


def _as_decimal(value, field):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a decimal amount.") from exc
    if not amount.is_finite() or amount < 0 or amount.as_tuple().exponent < -2:
        raise ValueError(f"{field} must be a non-negative amount with at most 2 decimals.")
    return amount


def _as_integer(value, field):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a whole number.") from exc
    if not number.is_finite() or number != number.to_integral_value():
        raise ValueError(f"{field} must be a whole number.")
    return int(number)


def _loan_opening_plan(values, branch_id, *, lock=False):
    member_code = str(values["member_code"] or "").strip()
    product_code = str(values["product_code"] or "").strip()
    members = Member.unscoped
    products = LoanProduct.objects
    if lock:
        members = members.select_for_update()
        products = products.select_for_update()
    member = members.filter(member_code=member_code, branch_id=branch_id).first()
    if member is None:
        raise ValueError("member_code is not in the selected branch.")
    product = products.filter(code=product_code).first()
    if product is None:
        raise ValueError("product_code does not identify a loan product.")

    principal = _as_decimal(values["disbursed_amount"], "disbursed_amount")
    outstanding = _as_decimal(values["outstanding_principal"], "outstanding_principal")
    accrued_interest = _as_decimal(
        values["accrued_unpaid_interest"], "accrued_unpaid_interest"
    )
    unpaid_penalties = _as_decimal(values["unpaid_penalties"], "unpaid_penalties")
    if principal <= 0 or outstanding <= 0:
        raise ValueError("disbursed_amount and outstanding_principal must be positive.")
    if outstanding > principal:
        raise ValueError("outstanding_principal cannot exceed disbursed_amount.")
    largest_amount = Decimal("9999999999999999.99")
    if any(
        value > largest_amount
        for value in (principal, outstanding, accrued_interest, unpaid_penalties)
    ):
        raise ValueError("Loan amounts exceed the supported precision.")

    term = _as_integer(values["term"], "term")
    overdue_installments = _as_integer(
        values["overdue_installments"], "overdue_installments"
    )
    if not 1 <= term <= min(product.max_term, 32767):
        raise ValueError("term must be within the product's remaining term limit.")
    if not 0 <= overdue_installments <= term:
        raise ValueError("overdue_installments must be between zero and term.")
    frequency = str(values["frequency"] or "").strip()
    if frequency not in dict(LoanProduct.FREQUENCY_CHOICES):
        raise ValueError("frequency must be weekly, bi_weekly, or monthly.")

    disbursed_date = _as_date(values["disbursed_date"], "disbursed_date")
    opening_date = _as_date(values["opening_date"], "opening_date")
    next_due_date = _as_date(values["next_due_date"], "next_due_date")
    if disbursed_date > opening_date:
        raise ValueError("disbursed_date cannot be after opening_date.")
    if next_due_date <= disbursed_date:
        raise ValueError("next_due_date must be after disbursed_date.")
    if opening_date > timezone.localdate():
        raise ValueError("opening_date cannot be in the future.")
    last_payment_date = None
    if values["last_payment_date"]:
        last_payment_date = _as_date(values["last_payment_date"], "last_payment_date")
        if not disbursed_date <= last_payment_date <= opening_date:
            raise ValueError(
                "last_payment_date must fall between disbursed_date and opening_date."
            )

    schedule = generate_schedule(
        outstanding,
        Decimal(product.annual_interest_rate) / 100,
        term,
        frequency,
        product.interest_method,
        next_due_date,
        holiday_convention=product.holiday_convention,
    )
    actual_overdue = sum(
        installment["due_date"] < opening_date
        for installment in schedule["installments"]
    )
    if actual_overdue != overdue_installments:
        raise ValueError(
            "overdue_installments does not match installments due before opening_date."
        )
    if unpaid_penalties and not overdue_installments:
        raise ValueError("unpaid_penalties requires at least one overdue installment.")
    if accrued_interest:
        schedule["installments"][0]["interest_due"] += accrued_interest
        schedule["installments"][0]["total_due"] += accrued_interest
        schedule["interest"] += accrued_interest
        schedule["total_repayable"] += accrued_interest
    if any(
        installment["principal_due"] > largest_amount
        or installment["interest_due"] > largest_amount
        for installment in schedule["installments"]
    ):
        raise ValueError("A scheduled installment exceeds the supported precision.")
    return {
        "member": member,
        "product": product,
        "principal": principal,
        "outstanding": outstanding,
        "accrued_interest": accrued_interest,
        "unpaid_penalties": unpaid_penalties,
        "term": term,
        "frequency": frequency,
        "disbursed_date": disbursed_date,
        "opening_date": opening_date,
        "next_due_date": next_due_date,
        "last_payment_date": last_payment_date,
        "schedule": schedule,
        "overdue_installments": overdue_installments,
    }


def validate_batch(batch):
    if batch.status != ImportBatch.STATUS_UPLOADED:
        raise ValidationError("Only uploaded batches can be validated.")
    rows = _read_rows(batch)
    if not rows:
        errors = [{"row": 0, "field": "", "message": "Workbook contains no data rows."}]
        batch.validation_errors = errors
        batch.row_count = 0
        batch.status = ImportBatch.STATUS_INVALID
        batch.save(update_fields=("validation_errors", "row_count", "status"))
        return errors
    errors = []
    seen = set()
    debit_total = Decimal("0.00")
    credit_total = Decimal("0.00")
    loan_principal_total = Decimal("0.00")
    loan_opening_date = None
    journal_date = None
    if batch.import_type == ImportBatch.TYPE_LOAN_OPENING:
        required_mappings = {
            mapping.key: mapping
            for mapping in SystemAccountMapping.objects.select_related("account").filter(
                key__in=("loans_to_members", "opening_balance_equity"),
                account__is_active=True,
                account__allows_direct_posting=True,
            )
        }
        if len(required_mappings) != 2:
            errors.append(
                {
                    "row": 0,
                    "field": "account mappings",
                    "message": (
                        "Active Loans to Members and Opening Balance Equity mappings "
                        "are required before import."
                    ),
                }
            )
        else:
            for mapping in required_mappings.values():
                try:
                    mapping.full_clean()
                except ValidationError as exc:
                    errors.append(
                        {
                            "row": 0,
                            "field": "account mappings",
                            "message": "; ".join(exc.messages)[:240],
                        }
                    )
    for row_number, values in rows:
        try:
            if batch.import_type == ImportBatch.TYPE_MEMBERS:
                member_code = str(values["member_code"] or "").strip()
                if not member_code:
                    raise ValueError("member_code is required.")
                if member_code in seen or Member.unscoped.filter(
                    member_code=member_code
                ).exists():
                    raise ValueError("member_code already exists.")
                seen.add(member_code)
                if not str(values["first_name"] or "").strip():
                    raise ValueError("first_name is required.")
                if not str(values["last_name"] or "").strip():
                    raise ValueError("last_name is required.")
                if values["email"]:
                    from django.core.validators import validate_email

                    validate_email(str(values["email"]).strip())
                for field in ("date_of_birth", "admission_date"):
                    if values[field]:
                        _as_date(values[field], field)
                member = Member(
                    branch_id=batch.branch_id,
                    member_code=member_code,
                    first_name=str(values["first_name"]).strip(),
                    last_name=str(values["last_name"]).strip(),
                    phone=str(values["phone"] or "").strip(),
                    email=str(values["email"] or "").strip(),
                    date_of_birth=_as_date(values["date_of_birth"], "date_of_birth")
                    if values["date_of_birth"]
                    else None,
                    admission_date=_as_date(values["admission_date"], "admission_date")
                    if values["admission_date"]
                    else timezone.localdate(),
                )
                member.full_clean()
            elif batch.import_type == ImportBatch.TYPE_SAVINGS_OPENING:
                account_number = str(values["account_number"] or "").strip()
                if account_number in seen:
                    raise ValueError("account_number appears more than once.")
                seen.add(account_number)
                account = SavingsAccount.unscoped.filter(
                    account_number=account_number,
                    branch_id=batch.branch_id,
                ).first()
                if account is None:
                    raise ValueError("Savings account is not in the selected branch.")
                if _as_decimal(values["amount"], "amount") <= 0:
                    raise ValueError("amount must be greater than zero.")
                _as_date(values["transaction_date"], "transaction_date")
            elif batch.import_type == ImportBatch.TYPE_GL_OPENING:
                account_code = str(values["account_code"] or "").strip()
                account = Account.objects.filter(
                    code=account_code,
                    is_active=True,
                    allows_direct_posting=True,
                ).first()
                if account is None:
                    raise ValueError("account_code must identify an active postable account.")
                debit = _as_decimal(values["debit"], "debit")
                credit = _as_decimal(values["credit"], "credit")
                if (debit > 0) == (credit > 0):
                    raise ValueError("Enter a positive debit or credit, but not both.")
                debit_total += debit
                credit_total += credit
                row_journal_date = _as_date(values["journal_date"], "journal_date")
                if journal_date is None:
                    journal_date = row_journal_date
                elif row_journal_date != journal_date:
                    raise ValueError("All opening GL rows must use the same journal date.")
            elif batch.import_type == ImportBatch.TYPE_LOAN_OPENING:
                member_code = str(values["member_code"] or "").strip()
                plan = _loan_opening_plan(values, batch.branch_id)
                loan_key = (member_code, plan["product"].pk)
                if loan_key in seen:
                    raise ValueError(
                        "A member and product may appear only once in this loan import."
                    )
                seen.add(loan_key)
                if loan_opening_date is None:
                    loan_opening_date = plan["opening_date"]
                elif plan["opening_date"] != loan_opening_date:
                    raise ValueError("All loan rows must use the same opening_date.")
                if Loan.unscoped.filter(
                    branch_id=batch.branch_id,
                    member=plan["member"],
                    product=plan["product"],
                    status=Loan.STATUS_ACTIVE,
                ).exists():
                    raise ValueError(
                        "The member already has an active loan for this product."
                    )
                loan_principal_total += plan["outstanding"]
        except (ValueError, ValidationError) as exc:
            message = "; ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)
            errors.append(
                {"row": row_number, "field": "", "message": message[:240]}
            )
    if (
        batch.import_type == ImportBatch.TYPE_GL_OPENING
        and debit_total != credit_total
    ):
        errors.append(
            {
                "row": 0,
                "field": "debit/credit",
                "message": "Opening journal debits and credits must balance to zero.",
            }
        )
    if batch.import_type == ImportBatch.TYPE_LOAN_OPENING and not rows:
        errors.append(
            {"row": 0, "field": "", "message": "Workbook contains no loan rows."}
        )
    if (
        batch.import_type == ImportBatch.TYPE_LOAN_OPENING
        and loan_principal_total > Decimal("9999999999999999.99")
    ):
        errors.append(
            {
                "row": 0,
                "field": "outstanding_principal",
                "message": "Total opening principal exceeds journal amount precision.",
            }
        )
    batch.validation_errors = errors
    batch.row_count = len(rows)
    batch.status = (
        ImportBatch.STATUS_INVALID if errors else ImportBatch.STATUS_VALIDATED
    )
    batch.save(update_fields=("validation_errors", "row_count", "status"))
    log_action(
        "Validate",
        "ImportBatch",
        batch.pk,
        new_values={"status": batch.status, "row_count": batch.row_count},
        branch_id=batch.branch_id,
    )
    return errors


@transaction.atomic
def confirm_batch(*, batch, user, request):
    ImportBatch.objects.select_for_update().get(pk=batch.pk)
    batch.refresh_from_db()
    if batch.status != ImportBatch.STATUS_VALIDATED:
        raise ValidationError("Only a successfully validated batch can be confirmed.")
    if batch.import_type in {
        ImportBatch.TYPE_SAVINGS_OPENING,
        ImportBatch.TYPE_GL_OPENING,
        ImportBatch.TYPE_LOAN_OPENING,
    }:
        batch.status = ImportBatch.STATUS_AWAITING_APPROVAL
        batch.save(update_fields=("status",))
        log_action(
            "SubmitForApproval",
            "ImportBatch",
            batch.pk,
            new_values={"status": batch.status},
            branch_id=batch.branch_id,
        )
        return batch
    _execute_import(batch=batch, user=user, request=request)
    return batch


@transaction.atomic
def approve_batch(*, batch, user, request):
    ImportBatch.objects.select_for_update().get(pk=batch.pk)
    batch.refresh_from_db()
    if batch.status != ImportBatch.STATUS_AWAITING_APPROVAL:
        raise ValidationError("This batch is not awaiting approval.")
    if batch.created_by_id == user.pk:
        raise ValidationError("The maker cannot approve their own opening-balance import.")
    if batch.import_type not in {
        ImportBatch.TYPE_SAVINGS_OPENING,
        ImportBatch.TYPE_GL_OPENING,
        ImportBatch.TYPE_LOAN_OPENING,
    }:
        raise ValidationError("Only opening-balance batches use maker-checker approval.")
    _execute_import(batch=batch, user=user, request=request)
    batch.approved_by = user
    batch.save(update_fields=("approved_by",))
    log_action(
        "Approve",
        "ImportBatch",
        batch.pk,
        new_values={"approved_by_id": user.pk, "status": batch.status},
        branch_id=batch.branch_id,
    )
    return batch


@transaction.atomic
def _execute_import(*, batch, user, request):
    try:
        return _execute_import_rows(batch=batch, user=user, request=request)
    except IntegrityError as exc:
        raise ValidationError(
            "The import conflicts with data that changed after validation."
        ) from exc


@transaction.atomic
def _execute_import_rows(*, batch, user, request):
    if batch.status not in {
        ImportBatch.STATUS_VALIDATED,
        ImportBatch.STATUS_AWAITING_APPROVAL,
    }:
        raise ValidationError("This batch is not ready to import.")
    rows = _read_rows(batch)
    if batch.import_type == ImportBatch.TYPE_MEMBERS:
        for _, values in rows:
            member = Member(
                branch_id=batch.branch_id,
                member_code=str(values["member_code"]).strip(),
                first_name=str(values["first_name"]).strip(),
                last_name=str(values["last_name"]).strip(),
                phone=str(values["phone"] or "").strip(),
                email=str(values["email"] or "").strip(),
                date_of_birth=_as_date(values["date_of_birth"], "date_of_birth")
                if values["date_of_birth"]
                else None,
                admission_date=_as_date(values["admission_date"], "admission_date")
                if values["admission_date"]
                else timezone.localdate(),
                created_by=user,
            )
            member.full_clean()
            member.save()
            log_action(
                "Create",
                "Member",
                member.pk,
                new_values={"member_code": member.member_code},
                branch_id=batch.branch_id,
            )
    elif batch.import_type == ImportBatch.TYPE_SAVINGS_OPENING:
        service = SavingsService(request)
        for row_number, values in rows:
            account = SavingsAccount.unscoped.get(
                account_number=str(values["account_number"]).strip(),
                branch_id=batch.branch_id,
            )
            key = uuid.uuid5(
                uuid.UUID(batch.file_hash[:32]),
                f"savings-opening-{row_number}",
            )
            service.deposit(
                account_id=account.pk,
                amount=_as_decimal(values["amount"], "amount"),
                transaction_date=_as_date(
                    values["transaction_date"], "transaction_date"
                ),
                payment_channel=SavingsTransaction.CHANNEL_CASH,
                idempotency_key=key,
                narration=f"Opening balance import {batch.file_hash[:12]}",
            )
    elif batch.import_type == ImportBatch.TYPE_GL_OPENING:
        first_date = _as_date(rows[0][1]["journal_date"], "journal_date")
        service = JournalService(request)
        entry = service.create_entry(
            branch_id=batch.branch_id,
            journal_date=first_date,
            narration=f"GL opening balances import {batch.file_hash[:12]}",
            source_type="gl_opening_import",
            source_id=str(batch.pk),
            idempotency_key=uuid.uuid5(
                uuid.UUID(batch.file_hash[:32]), "gl-opening-journal"
            ),
        )
        if not entry._idempotent_replay:
            for _, values in rows:
                account = Account.objects.get(
                    code=str(values["account_code"]).strip(),
                    is_active=True,
                    allows_direct_posting=True,
                )
                if _as_date(values["journal_date"], "journal_date") != first_date:
                    raise ValidationError(
                        "All opening GL rows must use the same journal date."
                    )
                service.add_line(
                    entry_id=entry.pk,
                    account_id=account.pk,
                    debit=_as_decimal(values["debit"], "debit"),
                    credit=_as_decimal(values["credit"], "credit"),
                    narration=str(values["narration"] or "")[:255],
                )
            service.post(entry_id=entry.pk)
    elif batch.import_type == ImportBatch.TYPE_LOAN_OPENING:
        _execute_loan_opening_rows(batch=batch, rows=rows, user=user, request=request)
    batch.status = ImportBatch.STATUS_IMPORTED
    batch.imported_at = timezone.now()
    batch.save(update_fields=("status", "imported_at"))
    log_action(
        "Import",
        "ImportBatch",
        batch.pk,
        new_values={"status": batch.status, "row_count": batch.row_count},
        branch_id=batch.branch_id,
    )
    file_name = batch.source_file.name
    transaction.on_commit(lambda: default_storage.delete(file_name))


def _execute_loan_opening_rows(*, batch, rows, user, request):
    if not rows:
        raise ValidationError("Workbook contains no loan rows.")
    plans = []
    seen_loans = set()
    for _, values in rows:
        plan = _loan_opening_plan(values, batch.branch_id, lock=True)
        loan_key = (plan["member"].pk, plan["product"].pk)
        if loan_key in seen_loans:
            raise ValidationError(
                "A member and product may appear only once in this loan import."
            )
        seen_loans.add(loan_key)
        if Loan.unscoped.select_for_update().filter(
            branch_id=batch.branch_id,
            member=plan["member"],
            product=plan["product"],
            status=Loan.STATUS_ACTIVE,
        ).exists():
            raise ValidationError(
                "The member already has an active loan for this product."
            )
        plans.append(plan)

    mappings = {
        mapping.key: mapping
        for mapping in SystemAccountMapping.objects.select_related("account")
        .select_for_update()
        .filter(key__in=("loans_to_members", "opening_balance_equity"))
    }
    if len(mappings) != 2:
        raise ValidationError("Loan opening-balance account mappings are incomplete.")
    for mapping in mappings.values():
        mapping.full_clean()
    journal_date = plans[0]["opening_date"]
    if any(plan["opening_date"] != journal_date for plan in plans):
        raise ValidationError("All loan rows must use the same opening_date.")

    journal_service = JournalService(request)
    entry = journal_service.create_entry(
        branch_id=batch.branch_id,
        journal_date=journal_date,
        narration=f"Loan opening balances import {batch.file_hash[:12]}",
        source_type="loan_opening_import",
        source_id=str(batch.pk),
        idempotency_key=uuid.uuid5(
            uuid.UUID(batch.file_hash[:32]), "loan-opening-journal"
        ),
    )
    if entry._idempotent_replay:
        raise ValidationError(
            "An opening journal already exists for this file; reconcile before retrying."
        )
    total_principal = sum((plan["outstanding"] for plan in plans), Decimal("0.00"))
    journal_service.add_line(
        entry_id=entry.pk,
        account_id=mappings["loans_to_members"].account_id,
        debit=total_principal,
        narration="Imported outstanding loan principal",
    )
    journal_service.add_line(
        entry_id=entry.pk,
        account_id=mappings["opening_balance_equity"].account_id,
        credit=total_principal,
        narration="Loan opening balance equity",
    )

    now = timezone.now()
    created_installments = []
    created_penalties = []
    for row_number, plan in zip((row[0] for row in rows), plans, strict=True):
        member = plan["member"]
        product = plan["product"]
        application_key = uuid.uuid5(
            uuid.UUID(batch.file_hash[:32]),
            f"loan-opening-application-{row_number}",
        )
        cycle_number = (
            LoanApplication.unscoped.filter(
                member=member,
                status=LoanApplication.STATUS_DISBURSED,
            ).count()
            + 1
        )
        application = LoanApplication.unscoped.create(
            branch_id=batch.branch_id,
            member=member,
            product=product,
            requested_amount=plan["principal"],
            approved_amount=plan["principal"],
            term=plan["term"],
            purpose=f"Opening balance import {batch.file_hash[:12]}",
            cycle_number=cycle_number,
            status=LoanApplication.STATUS_DISBURSED,
            idempotency_key=application_key,
            created_by=batch.created_by,
            reviewed_by=user,
            review_comment="Approved during maker-checker opening balance import.",
            submitted_at=now,
            reviewed_at=now,
        )
        loan_key = uuid.uuid5(
            uuid.UUID(batch.file_hash[:32]), f"loan-opening-loan-{row_number}"
        )
        loan = Loan.unscoped.create(
            branch_id=batch.branch_id,
            application=application,
            member=member,
            product=product,
            terms_snapshot={
                **product.snapshot_terms(),
                "installment_frequency": plan["frequency"],
                "opening_balance_import": {
                    "opening_date": plan["opening_date"].isoformat(),
                    "next_due_date": plan["next_due_date"].isoformat(),
                    "last_payment_date": (
                        plan["last_payment_date"].isoformat()
                        if plan["last_payment_date"]
                        else None
                    ),
                    "accrued_unpaid_interest": str(plan["accrued_interest"]),
                    "overdue_installments": plan["overdue_installments"],
                },
            },
            principal=plan["principal"],
            outstanding_principal=plan["outstanding"],
            effective_annual_rate=plan["schedule"]["effective_annual_rate"],
            status=Loan.STATUS_ACTIVE,
            disbursed_at=plan["disbursed_date"],
            disbursed_by=user,
            journal_entry=entry,
            accrued_penalty=plan["unpaid_penalties"],
            idempotency_key=loan_key,
        )
        for installment in plan["schedule"]["installments"]:
            created_installments.append(
                LoanInstallment(
                    loan=loan,
                    schedule_version=loan.schedule_version,
                    **{
                        key: value
                        for key, value in installment.items()
                        if key != "total_due"
                    },
                )
            )
        if plan["unpaid_penalties"]:
            first_overdue = next(
                installment
                for installment in plan["schedule"]["installments"]
                if installment["due_date"] < plan["opening_date"]
            )
            created_penalties.append(
                (loan, first_overdue["number"], plan["opening_date"],
                 plan["unpaid_penalties"])
            )
        LoanStatusHistory.objects.create(
            application=application,
            old_status="",
            new_status=LoanApplication.STATUS_DISBURSED,
            reason="Imported opening balance",
            changed_by=user,
        )
        LoanStatusHistory.objects.create(
            loan=loan,
            old_status="",
            new_status=loan.status,
            reason="Imported opening balance",
            changed_by=user,
        )
        log_action(
            "ImportDisburse",
            "LoanApplication",
            application.pk,
            new_values={
                "status": application.status,
                "approved_amount": str(application.approved_amount),
                "term": application.term,
                "loan_id": loan.pk,
            },
            branch_id=batch.branch_id,
        )
        log_action(
            "Create",
            "Loan",
            loan.pk,
            new_values={
                "principal": str(loan.principal),
                "outstanding_principal": str(loan.outstanding_principal),
                "accrued_unpaid_interest": str(plan["accrued_interest"]),
                "unpaid_penalties": str(plan["unpaid_penalties"]),
                "last_payment_date": (
                    plan["last_payment_date"].isoformat()
                    if plan["last_payment_date"]
                    else None
                ),
                "journal_entry_id": entry.pk,
            },
            branch_id=batch.branch_id,
        )
    LoanInstallment.objects.bulk_create(created_installments)
    installments_by_loan_and_number = {
        (installment.loan_id, installment.number): installment
        for installment in LoanInstallment.objects.filter(
            loan__journal_entry=entry
        )
    }
    LoanPenalty.objects.bulk_create(
        [
            LoanPenalty(
                installment=installments_by_loan_and_number[(loan.pk, number)],
                as_of_date=as_of_date,
                amount=amount,
            )
            for loan, number, as_of_date, amount in created_penalties
        ]
    )
    journal_service.post(entry_id=entry.pk)


def error_report_rows(batch):
    return [
        (
            error.get("row", ""),
            safe_report_cell(error.get("field", "")),
            safe_report_cell(error.get("message", "")),
        )
        for error in batch.validation_errors
    ]
