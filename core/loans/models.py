import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from core.common.managers import (
    BranchScopedManager,
    BranchScopedModel,
    BranchScopedQuerySet,
)


class ImmutableLoanPaymentQuerySet(BranchScopedQuerySet):
    def update(self, **kwargs):
        raise TypeError("Loan payments are immutable; post a correcting transaction.")

    def delete(self):
        raise TypeError("Loan payments are immutable; post a correcting transaction.")


ImmutableLoanPaymentManager = BranchScopedManager.from_queryset(
    ImmutableLoanPaymentQuerySet
)


class ImmutableLoanRecoveryQuerySet(BranchScopedQuerySet):
    def update(self, **kwargs):
        raise TypeError("Loan recoveries are immutable; post a correcting transaction.")

    def delete(self):
        raise TypeError("Loan recoveries are immutable; post a correcting transaction.")


ImmutableLoanRecoveryManager = BranchScopedManager.from_queryset(
    ImmutableLoanRecoveryQuerySet
)


class ImmutableLoanRescheduleQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise TypeError("Reschedule records are immutable.")

    def delete(self):
        raise TypeError("Reschedule records are immutable.")


ImmutableLoanRescheduleManager = models.Manager.from_queryset(
    ImmutableLoanRescheduleQuerySet
)


class LoanProduct(models.Model):
    METHOD_FLAT = "flat"
    METHOD_DECLINING = "declining"
    METHOD_CHOICES = [(METHOD_FLAT, "Flat"), (METHOD_DECLINING, "Declining balance")]
    FREQUENCY_WEEKLY = "weekly"
    FREQUENCY_BIWEEKLY = "bi_weekly"
    FREQUENCY_MONTHLY = "monthly"
    FREQUENCY_CHOICES = [
        (FREQUENCY_WEEKLY, "Weekly"),
        (FREQUENCY_BIWEEKLY, "Bi-weekly"),
        (FREQUENCY_MONTHLY, "Monthly"),
    ]
    PENALTY_DAILY = "daily"
    PENALTY_WEEKLY = "weekly"
    PENALTY_FREQUENCY_CHOICES = [
        (PENALTY_DAILY, "Per day"),
        (PENALTY_WEEKLY, "Per week"),
    ]
    HOLIDAY_NEXT = "next"
    HOLIDAY_PREVIOUS = "previous"
    HOLIDAY_KEEP = "keep"
    HOLIDAY_CHOICES = [
        (HOLIDAY_NEXT, "Next working day"),
        (HOLIDAY_PREVIOUS, "Previous working day"),
        (HOLIDAY_KEEP, "Keep date"),
    ]

    class Meta:
        db_table = "loan_products"
        ordering = ["code"]
        constraints = [
            models.CheckConstraint(
                condition=Q(min_amount__gt=0) & Q(max_amount__gte=models.F("min_amount")),
                name="loan_product_amount_range_valid",
            ),
            models.CheckConstraint(
                condition=Q(min_term__gt=0) & Q(max_term__gte=models.F("min_term")),
                name="loan_product_term_range_valid",
            ),
            models.CheckConstraint(
                condition=Q(annual_interest_rate__gte=0)
                & Q(annual_interest_rate__lte=100),
                name="loan_product_rate_valid",
            ),
        ]

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=120)
    interest_method = models.CharField(max_length=16, choices=METHOD_CHOICES)
    annual_interest_rate = models.DecimalField(max_digits=9, decimal_places=4)
    min_amount = models.DecimalField(max_digits=18, decimal_places=2)
    max_amount = models.DecimalField(max_digits=18, decimal_places=2)
    min_term = models.PositiveSmallIntegerField()
    max_term = models.PositiveSmallIntegerField()
    installment_frequency = models.CharField(max_length=16, choices=FREQUENCY_CHOICES)
    processing_fee = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal(0))
    processing_fee_rate = models.DecimalField(max_digits=9, decimal_places=4, default=Decimal(0))
    insurance_fee = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal(0))
    insurance_fee_rate = models.DecimalField(max_digits=9, decimal_places=4, default=Decimal(0))
    grace_period_days = models.PositiveSmallIntegerField(default=0)
    late_penalty_rate = models.DecimalField(max_digits=9, decimal_places=4, default=Decimal(0))
    penalty_grace_days = models.PositiveSmallIntegerField(default=0)
    penalty_frequency = models.CharField(
        max_length=8, choices=PENALTY_FREQUENCY_CHOICES, default=PENALTY_DAILY
    )
    penalty_cap_rate = models.DecimalField(max_digits=9, decimal_places=4, default=Decimal("0.25"))
    required_savings_rate = models.DecimalField(max_digits=9, decimal_places=4, default=Decimal(0))
    max_concurrent_loans = models.PositiveSmallIntegerField(default=1)
    cycle_limits = models.JSONField(default=dict, blank=True)
    approval_limit = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    early_settlement_fee = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal(0))
    holiday_convention = models.CharField(
        max_length=10, choices=HOLIDAY_CHOICES, default=HOLIDAY_NEXT
    )
    requires_verified_kyc = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True, db_index=True)

    def clean(self):
        errors = {}
        if self.annual_interest_rate is not None and not Decimal(0) <= self.annual_interest_rate <= Decimal(100):
            errors["annual_interest_rate"] = "Enter an annual percentage from 0 through 100."
        for field in (
            "processing_fee",
            "processing_fee_rate",
            "insurance_fee",
            "insurance_fee_rate",
            "late_penalty_rate",
            "penalty_cap_rate",
            "required_savings_rate",
            "early_settlement_fee",
        ):
            value = getattr(self, field)
            if value is not None and value < 0:
                errors[field] = "This value cannot be negative."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.code} — {self.name}"


class LoanApplication(BranchScopedModel):
    STATUS_DRAFT = "draft"
    STATUS_SUBMITTED = "submitted"
    STATUS_RETURNED = "returned"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_DISBURSED = "disbursed"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_SUBMITTED, "Submitted"),
        (STATUS_RETURNED, "Returned"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_DISBURSED, "Disbursed"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    class Meta:
        db_table = "loan_applications"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(requested_amount__gt=0), name="loan_application_amount_positive"),
            models.CheckConstraint(
                condition=Q(approved_amount__isnull=True)
                | Q(approved_amount__lte=models.F("requested_amount")),
                name="loan_application_approval_within_request",
            ),
            models.UniqueConstraint(fields=["created_by", "idempotency_key"], name="uniq_loan_application_key"),
        ]

    member = models.ForeignKey("branch.Member", on_delete=models.PROTECT, related_name="loan_applications")
    product = models.ForeignKey(LoanProduct, on_delete=models.PROTECT, related_name="applications")
    requested_amount = models.DecimalField(max_digits=18, decimal_places=2)
    approved_amount = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    term = models.PositiveSmallIntegerField()
    purpose = models.CharField(max_length=500)
    cycle_number = models.PositiveSmallIntegerField(default=1)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_DRAFT, db_index=True)
    idempotency_key = models.UUIDField(default=uuid.uuid4, editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="loan_applications_created")
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="loan_applications_reviewed")
    review_comment = models.CharField(max_length=500, blank=True, default="")
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        errors = {}
        if self.member_id and self.branch_id and self.member.branch_id != self.branch_id:
            errors["member"] = "The member must belong to the application branch."
        if self.product_id:
            if not self.product.is_active:
                errors["product"] = "Select an active loan product."
            if self.requested_amount is not None and not self.product.min_amount <= self.requested_amount <= self.product.max_amount:
                errors["requested_amount"] = "Amount is outside this product's limits."
            if self.term is not None and not self.product.min_term <= self.term <= self.product.max_term:
                errors["term"] = "Term is outside this product's limits."
        if errors:
            raise ValidationError(errors)


class Loan(BranchScopedModel):
    STATUS_ACTIVE = "active"
    STATUS_CLOSED = "closed"
    STATUS_WRITTEN_OFF = "written_off"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_CLOSED, "Closed"),
        (STATUS_WRITTEN_OFF, "Written off"),
    ]

    class Meta:
        db_table = "loans"
        ordering = ["-disbursed_at"]
        constraints = [
            models.CheckConstraint(condition=Q(principal__gt=0), name="loan_principal_positive"),
            models.CheckConstraint(condition=Q(outstanding_principal__gte=0), name="loan_principal_nonnegative"),
            models.CheckConstraint(
                condition=Q(outstanding_principal__lte=models.F("principal")),
                name="loan_outstanding_within_principal",
            ),
            models.CheckConstraint(
                condition=Q(recovered_amount__lte=models.F("written_off_amount")),
                name="loan_recovery_within_writeoff",
            ),
            models.UniqueConstraint(fields=["application"], name="uniq_loan_per_application"),
        ]

    application = models.OneToOneField(LoanApplication, on_delete=models.PROTECT, related_name="loan")
    member = models.ForeignKey("branch.Member", on_delete=models.PROTECT, related_name="loans")
    product = models.ForeignKey(LoanProduct, on_delete=models.PROTECT, related_name="loans")
    principal = models.DecimalField(max_digits=18, decimal_places=2)
    outstanding_principal = models.DecimalField(max_digits=18, decimal_places=2)
    effective_annual_rate = models.DecimalField(
        max_digits=9, decimal_places=4, default=Decimal(0)
    )
    written_off_amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal(0))
    recovered_amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal(0))
    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=STATUS_ACTIVE, db_index=True
    )
    disbursed_at = models.DateField()
    disbursement_channel = models.CharField(
        max_length=20,
        choices=[("cash_in_hand", "Cash"), ("bank_accounts", "Bank")],
        default="cash_in_hand",
    )
    disbursed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="loans_disbursed")
    journal_entry = models.ForeignKey("accounting.JournalEntry", on_delete=models.PROTECT, related_name="disbursed_loans")
    schedule_version = models.PositiveSmallIntegerField(default=1)
    accrued_penalty = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal(0))
    idempotency_key = models.UUIDField()
    write_off_idempotency_key = models.UUIDField(null=True, blank=True, unique=True)
    write_off_reason = models.CharField(max_length=500, blank=True, default="")
    closed_at = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def unrecovered_amount(self):
        return self.written_off_amount - self.recovered_amount


class LoanInstallment(models.Model):
    class Meta:
        db_table = "loan_installments"
        ordering = ["schedule_version", "number"]
        constraints = [
            models.UniqueConstraint(fields=["loan", "schedule_version", "number"], name="uniq_loan_schedule_row"),
            models.CheckConstraint(condition=Q(principal_due__gte=0) & Q(interest_due__gte=0) & Q(fee_due__gte=0), name="loan_installment_amounts_nonnegative"),
            models.CheckConstraint(
                condition=Q(principal_paid__lte=models.F("principal_due"))
                & Q(interest_paid__lte=models.F("interest_due"))
                & Q(interest_waived__lte=models.F("interest_due") - models.F("interest_paid"))
                & Q(fee_paid__lte=models.F("fee_due")),
                name="loan_installment_paid_within_due",
            ),
        ]

    loan = models.ForeignKey(Loan, on_delete=models.PROTECT, related_name="installments")
    schedule_version = models.PositiveSmallIntegerField()
    number = models.PositiveSmallIntegerField()
    due_date = models.DateField(db_index=True)
    principal_due = models.DecimalField(max_digits=18, decimal_places=2)
    interest_due = models.DecimalField(max_digits=18, decimal_places=2)
    fee_due = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal(0))
    principal_paid = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal(0))
    interest_paid = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal(0))
    interest_waived = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal(0))
    fee_paid = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal(0))

    @property
    def principal_remaining(self):
        return self.principal_due - self.principal_paid

    @property
    def interest_remaining(self):
        return self.interest_due - self.interest_paid - self.interest_waived

    @property
    def fee_remaining(self):
        return self.fee_due - self.fee_paid

    @property
    def total_due(self):
        return self.principal_remaining + self.interest_remaining + self.fee_remaining


class LoanPayment(BranchScopedModel):
    CHANNEL_CASH = "cash_in_hand"
    CHANNEL_BANK = "bank_accounts"
    CHANNEL_CHOICES = [
        (CHANNEL_CASH, "Cash"),
        (CHANNEL_BANK, "Bank"),
    ]
    class Meta:
        db_table = "loan_payments"
        ordering = ["-payment_date", "-pk"]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="loan_payment_amount_positive"),
            models.CheckConstraint(
                condition=Q(amount=models.F("principal_paid") + models.F("interest_paid") + models.F("fee_paid") + models.F("penalty_paid")),
                name="loan_payment_allocation_balanced",
            ),
            models.UniqueConstraint(fields=["loan", "idempotency_key"], name="uniq_loan_payment_key"),
        ]

    objects = ImmutableLoanPaymentManager()
    unscoped = models.Manager()

    loan = models.ForeignKey(Loan, on_delete=models.PROTECT, related_name="payments")
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    payment_channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES, default=CHANNEL_CASH)
    penalty_paid = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal(0))
    fee_paid = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal(0))
    interest_paid = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal(0))
    principal_paid = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal(0))
    advance_amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal(0))
    payment_date = models.DateField()
    idempotency_key = models.UUIDField()
    journal_entry = models.ForeignKey("accounting.JournalEntry", on_delete=models.PROTECT, related_name="loan_payments")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="loan_payments_created")
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.pk:
            raise TypeError("Loan payments are immutable; post a correcting transaction.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Loan payments are immutable; post a correcting transaction.")


class LoanHoliday(models.Model):
    class Meta:
        db_table = "loan_holidays"
        ordering = ["date"]

    date = models.DateField(unique=True)
    name = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)


class LoanPenalty(models.Model):
    class Meta:
        db_table = "loan_penalties"
        constraints = [
            models.UniqueConstraint(fields=["installment", "as_of_date"], name="uniq_loan_penalty_date"),
            models.CheckConstraint(
                condition=Q(amount__gte=0) & Q(paid__gte=0) & Q(paid__lte=models.F("amount")),
                name="loan_penalty_paid_within_amount",
            ),
        ]

    installment = models.ForeignKey(LoanInstallment, on_delete=models.PROTECT, related_name="penalties")
    as_of_date = models.DateField()
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    paid = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal(0))


class LoanRecovery(BranchScopedModel):
    class Meta:
        db_table = "loan_recoveries"
        ordering = ["-payment_date", "-pk"]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="loan_recovery_amount_positive"),
            models.UniqueConstraint(fields=["loan", "idempotency_key"], name="uniq_loan_recovery_key"),
        ]

    objects = ImmutableLoanRecoveryManager()
    unscoped = models.Manager()

    loan = models.ForeignKey(Loan, on_delete=models.PROTECT, related_name="recoveries")
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    payment_channel = models.CharField(
        max_length=20,
        choices=[("cash_in_hand", "Cash"), ("bank_accounts", "Bank")],
        default="cash_in_hand",
    )
    payment_date = models.DateField()
    idempotency_key = models.UUIDField()
    journal_entry = models.ForeignKey(
        "accounting.JournalEntry", on_delete=models.PROTECT, related_name="loan_recoveries"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="loan_recoveries_created"
    )

    def save(self, *args, **kwargs):
        if self.pk:
            raise TypeError("Loan recoveries are immutable; post a correcting transaction.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Loan recoveries are immutable; post a correcting transaction.")


class LoanReschedule(models.Model):
    class Meta:
        db_table = "loan_reschedules"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["loan", "idempotency_key"], name="uniq_loan_reschedule_key"
            )
        ]

    objects = ImmutableLoanRescheduleManager()

    loan = models.ForeignKey(Loan, on_delete=models.PROTECT, related_name="reschedules")
    previous_version = models.PositiveSmallIntegerField()
    schedule_version = models.PositiveSmallIntegerField()
    term = models.PositiveSmallIntegerField()
    effective_date = models.DateField()
    reason = models.CharField(max_length=500)
    idempotency_key = models.UUIDField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="loan_reschedules_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.pk:
            raise TypeError("Reschedule records are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Reschedule records are immutable.")
