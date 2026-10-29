import calendar
import uuid
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, localcontext

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Q, Sum
from django.utils import timezone

from core.accounting.models import (
    SystemAccountMapping,
    VoucherSequence,
)
from core.accounting.services import JournalService
from core.audit.services import log_action
from core.branch.models import Branch, Member, MemberKYC
from core.savings.models import SavingsAccount, SavingsProduct

from .models import (
    Loan,
    LoanApplication,
    LoanHoliday,
    LoanInstallment,
    LoanPayment,
    LoanPenalty,
    LoanProduct,
    LoanRecovery,
    LoanReschedule,
)

CENT = Decimal("0.01")
ZERO = Decimal("0.00")
PERIODS_PER_YEAR = {
    LoanProduct.FREQUENCY_WEEKLY: 52,
    LoanProduct.FREQUENCY_BIWEEKLY: 26,
    LoanProduct.FREQUENCY_MONTHLY: 12,
}


def money(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def generate_schedule(
    principal,
    annual_rate,
    term,
    frequency,
    method,
    first_due_date,
    *,
    holiday_convention=LoanProduct.HOLIDAY_NEXT,
):
    principal = money(principal)
    annual_rate = Decimal(annual_rate)
    if principal <= ZERO or term < 1:
        raise ValidationError("Principal and term must be positive.")
    if frequency not in PERIODS_PER_YEAR:
        raise ValidationError("Select a supported installment frequency.")
    periods_per_year = PERIODS_PER_YEAR[frequency]
    periodic_rate = annual_rate / periods_per_year
    with localcontext() as context:
        context.prec = 32
        if method == LoanProduct.METHOD_FLAT:
            total_interest = money(principal * annual_rate * Decimal(term) / periods_per_year)
            regular_payment = money((principal + total_interest) / term)
        elif method == LoanProduct.METHOD_DECLINING:
            if periodic_rate:
                factor = (Decimal(1) + periodic_rate) ** term
                regular_payment = money(
                    principal * periodic_rate * factor / (factor - Decimal(1))
                )
            else:
                regular_payment = money(principal / term)
            total_interest = None
        else:
            raise ValidationError("Select flat or declining-balance interest.")

        principal_remaining = principal
        rows = []
        for number in range(1, term + 1):
            due_date = _adjust_business_day(
                _due_after_installments(first_due_date, frequency, number - 1),
                holiday_convention,
            )
            if method == LoanProduct.METHOD_FLAT:
                interest = money(total_interest / term)
                principal_part = (
                    principal_remaining
                    if number == term
                    else money(principal / term)
                )
            else:
                interest = money(principal_remaining * periodic_rate)
                principal_part = (
                    principal_remaining
                    if number == term
                    else min(principal_remaining, regular_payment - interest)
                )
            principal_remaining -= principal_part
            rows.append(
                {
                    "number": number,
                    "due_date": due_date,
                    "principal_due": principal_part,
                    "interest_due": interest,
                    "fee_due": ZERO,
                    "total_due": principal_part + interest,
                }
            )

    total_interest = sum((row["interest_due"] for row in rows), ZERO)
    total_principal = sum((row["principal_due"] for row in rows), ZERO)
    if total_principal != principal:
        raise ValidationError("Schedule rounding failed to preserve principal.")
    return {
        "installment": regular_payment,
        "principal": total_principal,
        "interest": total_interest,
        "total_repayable": total_principal + total_interest,
        "effective_annual_rate": _effective_annual_rate(
            principal, regular_payment, term, periods_per_year
        ),
        "installments": rows,
    }


def _next_due_date(current, frequency):
    if frequency == LoanProduct.FREQUENCY_WEEKLY:
        return current + timedelta(days=7)
    if frequency == LoanProduct.FREQUENCY_BIWEEKLY:
        return current + timedelta(days=14)
    month_index = current.month - 1 + 1
    year = current.year + month_index // 12
    month = month_index % 12 + 1
    day = min(current.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _due_after_installments(anchor, frequency, periods):
    if frequency == LoanProduct.FREQUENCY_WEEKLY:
        return anchor + timedelta(days=7 * periods)
    if frequency == LoanProduct.FREQUENCY_BIWEEKLY:
        return anchor + timedelta(days=14 * periods)
    month_index = anchor.month - 1 + periods
    year = anchor.year + month_index // 12
    month = month_index % 12 + 1
    day = min(anchor.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _adjust_business_day(due_date, convention):
    if convention == LoanProduct.HOLIDAY_KEEP:
        return due_date
    step = 1 if convention == LoanProduct.HOLIDAY_NEXT else -1
    candidate = due_date
    while candidate.weekday() >= 5 or LoanHoliday.objects.filter(
        date=candidate, is_active=True
    ).exists():
        candidate += timedelta(days=step)
    return candidate


def _effective_annual_rate(principal, installment, term, periods_per_year):
    if installment * term <= principal:
        return ZERO
    low, high = Decimal(0), Decimal(1)
    for _ in range(100):
        rate = (low + high) / 2
        factor = (Decimal(1) + rate) ** term
        payment = principal * rate * factor / (factor - Decimal(1)) if rate else principal / term
        if payment < installment:
            low = rate
        else:
            high = rate
    return money(((Decimal(1) + (low + high) / 2) ** periods_per_year - 1) * 100)


class LoanService:
    def __init__(self, request):
        self.request = request

    def _ensure_access(self, branch_id):
        user = self.request.user
        if (
            not user.is_authenticated
            or not user.is_active
            or branch_id not in user.accessible_branch_ids(
                getattr(self.request, "active_branch_id", None)
            )
        ):
            raise ValidationError({"branch": "You cannot access this branch."})

    def _eligible(self, member, product, amount):
        if member.status != Member.STATUS_ACTIVE:
            raise ValidationError("Only active members may apply for a loan.")
        if product.requires_verified_kyc and not MemberKYC.objects.filter(
            member=member, status=MemberKYC.STATUS_VERIFIED
        ).exists():
            raise ValidationError("The member must have verified KYC.")
        active_loans = Loan.objects.filter(
            member=member, status=Loan.STATUS_ACTIVE
        ).count()
        if active_loans >= product.max_concurrent_loans:
            raise ValidationError("The member has reached the concurrent-loan limit.")
        if LoanInstallment.objects.filter(
            loan__member=member,
            loan__status=Loan.STATUS_ACTIVE,
            due_date__lt=timezone.localdate(),
        ).filter(
            Q(principal_paid__lt=F("principal_due"))
            | Q(interest_paid__lt=F("interest_due") - F("interest_waived"))
        ).exists():
            raise ValidationError("The member has overdue installments.")
        if product.required_savings_rate:
            compulsory = SavingsAccount.unscoped.filter(
                member=member,
                status=SavingsAccount.STATUS_ACTIVE,
                product__savings_type=SavingsProduct.TYPE_COMPULSORY,
            ).aggregate(total=Sum("balance"))["total"] or ZERO
            if compulsory < money(amount * product.required_savings_rate / 100):
                raise ValidationError("The required compulsory savings balance is not met.")
        cycle_number = Loan.objects.filter(member=member).count() + 1
        cycle_limit = product.cycle_limits.get(str(cycle_number))
        if cycle_limit is not None and amount > Decimal(str(cycle_limit)):
            raise ValidationError("Requested amount exceeds the member's loan-cycle limit.")
        return cycle_number

    @transaction.atomic
    def create_application(self, *, branch_id, member_id, product_id, amount, term, purpose, idempotency_key):
        amount = money(amount)
        try:
            idempotency_key = uuid.UUID(str(idempotency_key))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValidationError({"idempotency_key": "A valid idempotency key is required."}) from exc
        user = self.request.user
        replay = LoanApplication.objects.filter(
            created_by=user, idempotency_key=idempotency_key
        ).first()
        if replay:
            self._ensure_access(replay.branch_id)
            if (
                replay.branch_id != branch_id
                or replay.member_id != member_id
                or replay.product_id != product_id
                or replay.requested_amount != amount
                or replay.term != term
                or replay.purpose != purpose.strip()
            ):
                raise ValidationError(
                    {"idempotency_key": "This key was already used with different details."}
                )
            return replay
        branch = Branch.unscoped.select_for_update().filter(
            pk=branch_id, is_active=True
        ).first()
        if branch is None:
            raise ValidationError({"branch": "Select an active branch."})
        self._ensure_access(branch.pk)
        member = Member.unscoped.select_for_update().filter(
            pk=member_id, branch=branch
        ).first()
        product = LoanProduct.objects.select_for_update().filter(
            pk=product_id, is_active=True
        ).first()
        if member is None or product is None:
            raise ValidationError("Select a member and active product in this branch.")
        cycle_number = self._eligible(member, product, amount)
        application = LoanApplication(
            branch=branch,
            member=member,
            product=product,
            requested_amount=amount,
            term=term,
            purpose=purpose.strip(),
            cycle_number=cycle_number,
            created_by=user,
            idempotency_key=idempotency_key,
        )
        application.full_clean()
        application.save()
        log_action("Create", "LoanApplication", application.pk, new_values={"status": application.status, "amount": str(amount)}, branch_id=branch.pk)
        return application

    @transaction.atomic
    def submit(self, *, application_id):
        application = LoanApplication.objects.select_for_update().filter(pk=application_id).first()
        if application is None:
            raise LoanApplication.DoesNotExist
        self._ensure_access(application.branch_id)
        if application.status not in {LoanApplication.STATUS_DRAFT, LoanApplication.STATUS_RETURNED}:
            raise ValidationError("Only draft or returned applications can be submitted.")
        self._eligible(application.member, application.product, application.requested_amount)
        old_status = application.status
        application.status = LoanApplication.STATUS_SUBMITTED
        application.submitted_at = timezone.now()
        application.full_clean()
        application.save(update_fields=["status", "submitted_at", "updated_at"])
        log_action("Submit", "LoanApplication", application.pk, old_values={"status": old_status}, new_values={"status": application.status}, branch_id=application.branch_id)
        return application

    @transaction.atomic
    def review(self, *, application_id, decision, comment, approved_amount=None):
        application = LoanApplication.objects.select_for_update().filter(pk=application_id).first()
        if application is None:
            raise LoanApplication.DoesNotExist
        self._ensure_access(application.branch_id)
        if application.status != LoanApplication.STATUS_SUBMITTED:
            raise ValidationError("Only submitted applications can be reviewed.")
        if application.created_by_id == self.request.user.pk:
            raise ValidationError("The application maker cannot review their own application.")
        if not comment.strip():
            raise ValidationError({"comment": "A review comment is required."})
        if decision not in {
            LoanApplication.STATUS_APPROVED,
            LoanApplication.STATUS_REJECTED,
            LoanApplication.STATUS_RETURNED,
        }:
            raise ValidationError("Select approve, reject, or return.")
        amount = None
        if decision == LoanApplication.STATUS_APPROVED:
            amount = money(
                application.requested_amount
                if approved_amount is None
                else approved_amount
            )
            if amount <= ZERO or amount > application.requested_amount:
                raise ValidationError({"approved_amount": "Approved amount must be positive and no greater than requested."})
            if not application.product.min_amount <= amount <= application.product.max_amount:
                raise ValidationError(
                    {"approved_amount": "Approved amount is outside this product's limits."}
                )
            limit = application.product.approval_limit
            if limit is not None and amount > limit and not self.request.user.is_superuser:
                raise ValidationError("This amount exceeds the configured approver limit.")
        old_status = application.status
        application.status = decision
        application.approved_amount = amount
        application.reviewed_by = self.request.user
        application.review_comment = comment.strip()
        application.reviewed_at = timezone.now()
        application.save(update_fields=["status", "approved_amount", "reviewed_by", "review_comment", "reviewed_at", "updated_at"])
        log_action(decision.title(), "LoanApplication", application.pk, old_values={"status": old_status}, new_values={"status": decision, "approved_amount": str(amount) if amount else None}, remarks=comment, branch_id=application.branch_id)
        return application

    @transaction.atomic
    def disburse(self, *, application_id, disbursement_date, channel, idempotency_key):
        application = LoanApplication.objects.select_for_update().filter(pk=application_id).first()
        if application is None:
            raise LoanApplication.DoesNotExist
        self._ensure_access(application.branch_id)
        existing = Loan.objects.select_for_update().filter(application=application).first()
        if existing:
            if (
                existing.idempotency_key != self._uuid(idempotency_key)
                or existing.disbursed_at != disbursement_date
                or existing.disbursement_channel != channel
            ):
                raise ValidationError(
                    {"idempotency_key": "This application was disbursed with different details."}
                )
            return existing
        if application.status != LoanApplication.STATUS_APPROVED:
            raise ValidationError("Only approved applications can be disbursed.")
        if application.reviewed_by_id == self.request.user.pk:
            raise ValidationError("The approver cannot disburse the same application.")
        if channel not in {"cash_in_hand", "bank_accounts"}:
            raise ValidationError("Select cash or bank disbursement.")
        amount = application.approved_amount
        product = application.product
        processing = money(product.processing_fee + amount * product.processing_fee_rate / 100)
        insurance = money(product.insurance_fee + amount * product.insurance_fee_rate / 100)
        total_fees = processing + insurance
        if total_fees >= amount:
            raise ValidationError("Disbursement fees must be less than the approved principal.")
        key = self._uuid(idempotency_key)
        journal = self._journal(
            branch_id=application.branch_id,
            journal_date=disbursement_date,
            narration=f"Loan disbursement for {application.member.member_code}",
            idempotency_key=key,
            source_type="loan_disbursement",
            source_id=application.pk,
            lines=[
                ("loans_to_members", amount, ZERO, "Loan principal"),
                (channel, ZERO, amount - total_fees, "Net disbursement"),
                *(
                    [("fee_income", ZERO, total_fees, "Processing and insurance fees")]
                    if total_fees
                    else []
                ),
            ],
        )
        loan = Loan(
            branch_id=application.branch_id,
            application=application,
            member=application.member,
            product=product,
            principal=amount,
            outstanding_principal=amount,
            disbursed_at=disbursement_date,
            disbursement_channel=channel,
            disbursed_by=self.request.user,
            journal_entry=journal,
            idempotency_key=key,
        )
        loan.full_clean()
        loan.save()
        first_due_date = (
            disbursement_date + timedelta(days=product.grace_period_days)
            if product.grace_period_days
            else _next_due_date(disbursement_date, product.installment_frequency)
        )
        schedule = generate_schedule(
            amount,
            product.annual_interest_rate / 100,
            application.term,
            product.installment_frequency,
            product.interest_method,
            first_due_date,
            holiday_convention=product.holiday_convention,
        )
        loan.effective_annual_rate = schedule["effective_annual_rate"]
        loan.save(update_fields=["effective_annual_rate"])
        LoanInstallment.objects.bulk_create(
            [
                LoanInstallment(
                    loan=loan,
                    schedule_version=loan.schedule_version,
                    **{key: value for key, value in row.items() if key != "total_due"},
                )
                for row in schedule["installments"]
            ]
        )
        application.status = LoanApplication.STATUS_DISBURSED
        application.save(update_fields=["status", "updated_at"])
        log_action("Disburse", "Loan", loan.pk, new_values={"principal": str(amount), "journal_entry_id": journal.pk}, branch_id=loan.branch_id)
        return loan

    @transaction.atomic
    def repay(
        self,
        *,
        loan_id,
        amount,
        payment_date,
        idempotency_key,
        payment_channel=LoanPayment.CHANNEL_CASH,
        include_future=False,
    ):
        loan = Loan.objects.select_for_update().filter(pk=loan_id).first()
        if loan is None:
            raise Loan.DoesNotExist
        self._ensure_access(loan.branch_id)
        key = self._uuid(idempotency_key)
        amount = money(amount)
        replay = LoanPayment.objects.filter(loan=loan, idempotency_key=key).first()
        if replay:
            if (
                replay.amount != amount
                or replay.payment_date != payment_date
                or replay.payment_channel != payment_channel
            ):
                raise ValidationError(
                    {"idempotency_key": "This key was already used with different details."}
                )
            return replay
        if loan.status != Loan.STATUS_ACTIVE:
            raise ValidationError("Only active loans accept repayments.")
        if payment_channel not in dict(LoanPayment.CHANNEL_CHOICES):
            raise ValidationError({"payment_channel": "Select cash or bank."})
        if amount <= ZERO:
            raise ValidationError({"amount": "Payment must be greater than zero."})
        self._ensure_payment_date(loan, payment_date)
        installments = list(
            LoanInstallment.objects.select_for_update()
            .filter(loan=loan, schedule_version=loan.schedule_version)
            .order_by("due_date", "number")
        )
        penalty_due = self._assess_penalties(loan, installments, payment_date)
        outstanding_fees = sum((row.fee_remaining for row in installments), ZERO)
        outstanding_interest = sum((row.interest_remaining for row in installments), ZERO)
        if amount > loan.outstanding_principal + outstanding_fees + outstanding_interest + penalty_due:
            raise ValidationError({"amount": "Overpayment is not allowed; refund or savings transfer must be handled separately."})

        remaining = amount
        penalty_paid = min(remaining, penalty_due)
        remaining -= penalty_paid
        fee_paid = self._apply_to_installments(
            installments,
            remaining,
            "fee",
            as_of_date=payment_date,
            include_future=include_future,
        )
        remaining -= fee_paid
        interest_paid = self._apply_to_installments(
            installments,
            remaining,
            "interest",
            as_of_date=payment_date,
            include_future=include_future,
        )
        remaining -= interest_paid
        principal_paid = self._apply_to_installments(
            installments,
            remaining,
            "principal",
            as_of_date=payment_date,
            include_future=include_future,
        )
        remaining -= principal_paid
        advance_amount = ZERO
        if remaining:
            advance_amount = self._apply_to_installments(
                installments,
                remaining,
                "principal",
                include_future=True,
                as_of_date=payment_date,
            )
            principal_paid += advance_amount
            remaining -= advance_amount
        if remaining:
            raise ValidationError("Payment exceeds outstanding loan obligations.")
        for row in installments:
            row.save(update_fields=["principal_paid", "interest_paid", "fee_paid"])
        self._apply_penalty_payment(installments, penalty_paid)
        loan.accrued_penalty = (
            LoanPenalty.objects.filter(installment__loan=loan).aggregate(
                total=Sum(F("amount") - F("paid"))
            )["total"]
            or ZERO
        )
        loan.outstanding_principal -= principal_paid
        if loan.outstanding_principal < ZERO:
            raise ValidationError("Payment would overpay principal.")
        if loan.outstanding_principal == ZERO and all(row.interest_remaining == ZERO and row.fee_remaining == ZERO for row in installments):
            loan.status = Loan.STATUS_CLOSED
            loan.closed_at = payment_date
        journal = self._journal(
            branch_id=loan.branch_id,
            journal_date=payment_date,
            narration=f"Loan repayment for {loan.member.member_code}",
            idempotency_key=key,
            source_type="loan_repayment",
            source_id=key,
            lines=[
                (payment_channel, amount, ZERO, "Loan repayment received"),
                *self._credit_lines(
                    [
                        ("loans_to_members", principal_paid, "Principal"),
                        ("interest_income", interest_paid, "Interest"),
                        ("penalty_income", penalty_paid, "Penalty"),
                        ("fee_income", fee_paid, "Fees"),
                    ]
                ),
            ],
        )
        loan.save(
            update_fields=[
                "outstanding_principal",
                "accrued_penalty",
                "status",
                "closed_at",
            ]
        )
        payment = LoanPayment.objects.create(
            branch_id=loan.branch_id,
            loan=loan,
            amount=amount,
            payment_channel=payment_channel,
            penalty_paid=penalty_paid,
            fee_paid=fee_paid,
            interest_paid=interest_paid,
            principal_paid=principal_paid,
            advance_amount=advance_amount,
            payment_date=payment_date,
            idempotency_key=key,
            journal_entry=journal,
            created_by=self.request.user,
        )
        log_action("Repay", "LoanPayment", payment.pk, new_values={"amount": str(amount), "principal": str(principal_paid), "interest": str(interest_paid), "penalty": str(penalty_paid)}, branch_id=loan.branch_id)
        return payment

    @transaction.atomic
    def reschedule(
        self, *, loan_id, new_term, effective_date, reason, idempotency_key
    ):
        loan = Loan.objects.select_for_update().filter(pk=loan_id, status=Loan.STATUS_ACTIVE).first()
        if loan is None:
            raise Loan.DoesNotExist
        self._ensure_access(loan.branch_id)
        key = self._uuid(idempotency_key)
        replay = LoanReschedule.objects.filter(loan=loan, idempotency_key=key).first()
        if replay:
            if (
                replay.term != new_term
                or replay.effective_date != effective_date
                or replay.reason != reason.strip()
            ):
                raise ValidationError(
                    {"idempotency_key": "This key was already used with different details."}
                )
            return loan
        if loan.status != Loan.STATUS_ACTIVE:
            raise ValidationError("Only active loans can be rescheduled.")
        if not reason.strip() or not loan.product.min_term <= new_term <= loan.product.max_term:
            raise ValidationError("A valid product term and reason are required.")
        if loan.disbursed_by_id == self.request.user.pk:
            raise ValidationError("The disburser cannot approve a reschedule.")
        self._ensure_payment_date(loan, effective_date)
        old_version = loan.schedule_version
        old_schedule = list(
            LoanInstallment.objects.select_for_update().filter(
                loan=loan, schedule_version=old_version
            )
        )
        accrued_interest = sum(
            (
                row.interest_remaining
                for row in old_schedule
                if row.due_date <= effective_date
            ),
            ZERO,
        )
        for row in old_schedule:
            if row.due_date > effective_date:
                row.interest_waived += row.interest_remaining
                row.save(update_fields=["interest_waived"])
        next_version = old_version + 1
        schedule = generate_schedule(
            loan.outstanding_principal,
            loan.product.annual_interest_rate / 100,
            new_term,
            loan.product.installment_frequency,
            loan.product.interest_method,
            _next_due_date(effective_date, loan.product.installment_frequency),
            holiday_convention=loan.product.holiday_convention,
        )
        if schedule["installments"] and accrued_interest:
            schedule["installments"][0]["interest_due"] += accrued_interest
            schedule["installments"][0]["total_due"] += accrued_interest
        LoanInstallment.objects.bulk_create(
            [
                LoanInstallment(
                    loan=loan,
                    schedule_version=next_version,
                    **{key: value for key, value in row.items() if key != "total_due"},
                )
                for row in schedule["installments"]
            ]
        )
        loan.schedule_version = next_version
        loan.effective_annual_rate = schedule["effective_annual_rate"]
        loan.save(update_fields=["schedule_version", "effective_annual_rate"])
        LoanReschedule.objects.create(
            loan=loan,
            previous_version=old_version,
            schedule_version=next_version,
            term=new_term,
            effective_date=effective_date,
            reason=reason.strip(),
            idempotency_key=key,
            created_by=self.request.user,
        )
        log_action(
            "Reschedule",
            "Loan",
            loan.pk,
            old_values={"schedule_version": old_version},
            new_values={
                "schedule_version": loan.schedule_version,
                "term": new_term,
                "accrued_interest_carried": str(accrued_interest),
            },
            remarks=reason.strip(),
            branch_id=loan.branch_id,
        )
        return loan

    @transaction.atomic
    def settle(self, *, loan_id, settlement_date, idempotency_key):
        loan = Loan.objects.select_for_update().filter(pk=loan_id).first()
        if loan is None:
            raise Loan.DoesNotExist
        self._ensure_access(loan.branch_id)
        key = self._uuid(idempotency_key)
        replay = LoanPayment.objects.filter(loan=loan, idempotency_key=key).first()
        if replay:
            if replay.payment_date != settlement_date:
                raise ValidationError(
                    {"idempotency_key": "This key was already used with a different date."}
                )
            return replay
        if loan.status != Loan.STATUS_ACTIVE:
            raise ValidationError("Only active loans can be settled.")
        self._ensure_payment_date(loan, settlement_date)
        schedules = list(
            LoanInstallment.objects.select_for_update()
            .filter(loan=loan, schedule_version=loan.schedule_version)
            .order_by("due_date")
        )
        due_interest = sum(
            (
                row.interest_remaining
                for row in schedules
                if row.due_date <= settlement_date
            ),
            ZERO,
        )
        for row in schedules:
            if row.due_date > settlement_date:
                row.interest_waived += row.interest_remaining
                row.save(update_fields=["interest_waived"])
        fee_row = next((row for row in schedules if row.due_date <= settlement_date), None)
        if fee_row is None and schedules:
            fee_row = schedules[0]
        if fee_row and loan.product.early_settlement_fee:
            fee_row.fee_due += loan.product.early_settlement_fee
            fee_row.save(update_fields=["fee_due"])
        penalty_due = self._assess_penalties(loan, schedules, settlement_date)
        outstanding_fees = sum((row.fee_remaining for row in schedules), ZERO)
        amount = loan.outstanding_principal + due_interest + outstanding_fees + penalty_due
        payment = self.repay(
            loan_id=loan.pk,
            amount=amount,
            payment_date=settlement_date,
            idempotency_key=key,
            include_future=True,
        )
        log_action("Settle", "Loan", loan.pk, new_values={"payment_id": payment.pk}, branch_id=loan.branch_id)
        return payment

    @transaction.atomic
    def write_off(self, *, loan_id, write_off_date, reason, idempotency_key):
        loan = Loan.objects.select_for_update().filter(pk=loan_id).first()
        if loan is None:
            raise Loan.DoesNotExist
        self._ensure_access(loan.branch_id)
        key = self._uuid(idempotency_key)
        if loan.status == Loan.STATUS_WRITTEN_OFF:
            if (
                loan.write_off_idempotency_key == key
                and loan.closed_at == write_off_date
                and loan.write_off_reason == reason.strip()
            ):
                return loan
            raise ValidationError("This loan has already been written off.")
        if loan.status != Loan.STATUS_ACTIVE:
            raise ValidationError("Only active loans can be written off.")
        self._ensure_payment_date(loan, write_off_date)
        if self.request.user.pk in {
            loan.application.created_by_id,
            loan.disbursed_by_id,
            loan.application.reviewed_by_id,
        } or not reason.strip():
            raise ValidationError("A different checker and a write-off reason are required.")
        amount = loan.outstanding_principal
        if amount <= ZERO:
            raise ValidationError("There is no principal balance to write off.")
        for installment in LoanInstallment.objects.select_for_update().filter(
            loan=loan, schedule_version=loan.schedule_version
        ):
            installment.interest_waived += installment.interest_remaining
            installment.save(update_fields=["interest_waived"])
        journal = self._journal(
            branch_id=loan.branch_id,
            journal_date=write_off_date,
            narration=f"Write off loan {loan.pk}",
            idempotency_key=key,
            source_type="loan_write_off",
            source_id=loan.pk,
            lines=[
                ("loan_loss_provision", amount, ZERO, "Loan loss provision"),
                ("loans_to_members", ZERO, amount, "Loan principal written off"),
            ],
        )
        loan.outstanding_principal = ZERO
        loan.written_off_amount = amount
        loan.write_off_idempotency_key = key
        loan.write_off_reason = reason.strip()
        loan.status = Loan.STATUS_WRITTEN_OFF
        loan.closed_at = write_off_date
        loan.save(
            update_fields=[
                "outstanding_principal",
                "written_off_amount",
                "write_off_idempotency_key",
                "write_off_reason",
                "status",
                "closed_at",
            ]
        )
        log_action("WriteOff", "Loan", loan.pk, new_values={"status": loan.status, "journal_entry_id": journal.pk}, remarks=reason.strip(), branch_id=loan.branch_id)
        return loan

    @transaction.atomic
    def recover(self, *, loan_id, amount, payment_date, payment_channel, idempotency_key):
        loan = Loan.objects.select_for_update().filter(
            pk=loan_id, status=Loan.STATUS_WRITTEN_OFF
        ).first()
        if loan is None:
            raise Loan.DoesNotExist
        self._ensure_access(loan.branch_id)
        key = self._uuid(idempotency_key)
        replay = LoanRecovery.objects.filter(loan=loan, idempotency_key=key).first()
        amount = money(amount)
        if replay:
            if (
                replay.amount != amount
                or replay.payment_date != payment_date
                or replay.payment_channel != payment_channel
            ):
                raise ValidationError(
                    "This recovery key was already used with different details."
                )
            return replay
        if amount <= ZERO or amount > loan.written_off_amount - loan.recovered_amount:
            raise ValidationError(
                {"amount": "Recovery must be within the unrecovered write-off balance."}
            )
        if payment_channel not in dict(LoanPayment.CHANNEL_CHOICES):
            raise ValidationError({"payment_channel": "Select cash or bank."})
        self._ensure_payment_date(loan, payment_date)
        journal = self._journal(
            branch_id=loan.branch_id,
            journal_date=payment_date,
            narration=f"Recovery of written-off loan {loan.pk}",
            idempotency_key=key,
            source_type="loan_recovery",
            source_id=f"{loan.pk}:{key}",
            lines=[
                (payment_channel, amount, ZERO, "Recovery received"),
                ("recovery_income", ZERO, amount, "Written-off loan recovery"),
            ],
        )
        recovery = LoanRecovery.objects.create(
            branch_id=loan.branch_id,
            loan=loan,
            amount=amount,
            payment_channel=payment_channel,
            payment_date=payment_date,
            idempotency_key=key,
            journal_entry=journal,
            created_by=self.request.user,
        )
        loan.recovered_amount += amount
        loan.save(update_fields=["recovered_amount"])
        log_action(
            "Recover",
            "LoanRecovery",
            recovery.pk,
            new_values={"amount": str(amount), "journal_entry_id": journal.pk},
            branch_id=loan.branch_id,
        )
        return recovery

    @staticmethod
    def _ensure_payment_date(loan, payment_date):
        if payment_date < loan.disbursed_at:
            raise ValidationError("A loan transaction cannot predate disbursement.")
        latest_payment_date = loan.payments.order_by("-payment_date").values_list(
            "payment_date", flat=True
        ).first()
        if latest_payment_date and payment_date < latest_payment_date:
            raise ValidationError("A loan transaction cannot be backdated before a payment.")

    def portfolio(self, *, as_of_date, branch_ids):
        loans = Loan.objects.filter(
            branch_id__in=branch_ids, status=Loan.STATUS_ACTIVE
        ).select_related("member", "product")
        principal_total = loans.aggregate(total=Sum("outstanding_principal"))["total"] or ZERO
        par_amounts = {}
        for days in (1, 30, 90):
            at_risk = ZERO
            for loan in loans:
                oldest_due = LoanInstallment.objects.filter(
                    loan=loan, schedule_version=loan.schedule_version,
                    due_date__lt=as_of_date - timedelta(days=days),
                ).filter(
                    Q(principal_paid__lt=F("principal_due"))
                    | Q(interest_paid__lt=F("interest_due") - F("interest_waived"))
                ).order_by("due_date").first()
                if oldest_due:
                    at_risk += loan.outstanding_principal
            par_amounts[days] = {
                "amount": at_risk,
                "percentage": money(at_risk / principal_total * 100) if principal_total else ZERO,
            }
        return {"loans": loans, "principal": principal_total, "par": par_amounts}

    def _assess_penalties(self, loan, installments, payment_date):
        total = ZERO
        for installment in installments:
            overdue = installment.principal_remaining + installment.interest_remaining + installment.fee_remaining
            overdue_days = (payment_date - installment.due_date).days - loan.product.penalty_grace_days
            if overdue <= ZERO or overdue_days <= 0 or loan.product.late_penalty_rate <= 0:
                continue
            period_days = (
                7
                if loan.product.penalty_frequency == LoanProduct.PENALTY_WEEKLY
                else 1
            )
            periods = Decimal((overdue_days + period_days - 1) // period_days)
            target = money(overdue * loan.product.late_penalty_rate / 100 * periods)
            cap = money(installment.principal_due * loan.product.penalty_cap_rate / 100)
            target = min(target, cap)
            previous = LoanPenalty.objects.filter(installment=installment).aggregate(total=Sum("amount"))["total"] or ZERO
            if target > previous:
                increment = target - previous
                penalty, created = LoanPenalty.objects.get_or_create(
                    installment=installment,
                    as_of_date=payment_date,
                    defaults={"amount": increment},
                )
                if not created:
                    penalty.amount += increment
                    penalty.save(update_fields=["amount"])
                log_action(
                    "AssessPenalty",
                    "LoanPenalty",
                    penalty.pk,
                    new_values={
                        "amount": str(penalty.amount),
                        "as_of_date": str(payment_date),
                    },
                    branch_id=loan.branch_id,
                )
            total += max(ZERO, target - sum(
                (penalty.paid for penalty in LoanPenalty.objects.filter(installment=installment)),
                ZERO,
            ))
        return total

    def _apply_penalty_payment(self, installments, amount):
        remaining = amount
        for installment in installments:
            penalties = LoanPenalty.objects.select_for_update().filter(
                installment=installment
            ).order_by("as_of_date", "pk")
            for penalty in penalties:
                available = penalty.amount - penalty.paid
                paid = min(remaining, available)
                penalty.paid += paid
                if paid:
                    penalty.save(update_fields=["paid"])
                remaining -= paid
                if remaining <= ZERO:
                    return
        if remaining > ZERO:
            raise ValidationError("Penalty allocation does not match the assessed balance.")

    def _apply_to_installments(
        self, installments, amount, component, *, include_future=False, as_of_date
    ):
        remaining = amount
        applied = ZERO
        for row in installments:
            if not include_future and row.due_date > as_of_date:
                continue
            field = f"{component}_remaining"
            paid_field = f"{component}_paid"
            due = getattr(row, field)
            value = min(remaining, due)
            setattr(row, paid_field, getattr(row, paid_field) + value)
            applied += value
            remaining -= value
            if remaining <= ZERO:
                break
        return applied

    def _journal(self, *, branch_id, journal_date, narration, idempotency_key, source_type, source_id, lines):
        journal_service = JournalService(self.request)
        journal_key = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"erp-loans:{source_type}:{source_id}:{self.request.user.pk}:{idempotency_key}",
        )
        entry = journal_service.create_entry(
            branch_id=branch_id,
            journal_date=journal_date,
            narration=narration,
            voucher_type=VoucherSequence.VOUCHER_SYSTEM,
            source_type=source_type,
            source_id=str(source_id),
            idempotency_key=journal_key,
        )
        if getattr(entry, "_idempotent_replay", False):
            return entry
        for mapping_key, debit, credit, line_narration in lines:
            if debit == ZERO and credit == ZERO:
                continue
            account = SystemAccountMapping.objects.select_related("account").filter(
                key=mapping_key
            ).values_list("account_id", flat=True).first()
            if account is None:
                raise ValidationError(
                    f"Configure the {mapping_key} system-account mapping before posting."
                )
            journal_service.add_line(
                entry_id=entry.pk,
                account_id=account,
                debit=debit,
                credit=credit,
                narration=line_narration,
            )
        return journal_service.post(entry_id=entry.pk)

    @staticmethod
    def _credit_lines(items):
        return [(key, ZERO, amount, label) for key, amount, label in items if amount]

    @staticmethod
    def _uuid(value):
        try:
            return uuid.UUID(str(value))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValidationError({"idempotency_key": "A valid idempotency key is required."}) from exc
