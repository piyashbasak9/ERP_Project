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


class CollectionSheetQuerySet(BranchScopedQuerySet):
    def update(self, **kwargs):
        if kwargs.get("status") == CollectionSheet.STATUS_POSTED:
            raise TypeError("Use CollectionService to post collection sheets.")
        if kwargs.get("status") == CollectionSheet.STATUS_REVERSED:
            raise TypeError("Use CollectionService to reverse collection sheets.")
        if self.filter(status=CollectionSheet.STATUS_POSTED).exists():
            raise TypeError("Posted collection sheets are immutable.")
        if self.filter(status=CollectionSheet.STATUS_REVERSED).exists():
            raise TypeError("Reversed collection sheets are immutable.")
        return super().update(**kwargs)

    def delete(self):
        if self.filter(status=CollectionSheet.STATUS_POSTED).exists():
            raise TypeError("Posted collection sheets cannot be deleted; reverse the posting.")
        if self.filter(status=CollectionSheet.STATUS_REVERSED).exists():
            raise TypeError("Reversed collection sheets cannot be deleted.")
        return super().delete()


class CollectionItemQuerySet(BranchScopedQuerySet):
    def update(self, **kwargs):
        if self.filter(
            sheet__status__in=[
                CollectionSheet.STATUS_POSTED,
                CollectionSheet.STATUS_REVERSED,
            ]
        ).exists():
            raise TypeError("Rows on posted collection sheets are immutable.")
        return super().update(**kwargs)

    def delete(self):
        if self.filter(
            sheet__status__in=[
                CollectionSheet.STATUS_POSTED,
                CollectionSheet.STATUS_REVERSED,
            ]
        ).exists():
            raise TypeError("Rows on posted collection sheets cannot be deleted.")
        return super().delete()


class CollectionPostingQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise TypeError("Collection postings are immutable.")

    def delete(self):
        raise TypeError("Collection postings are immutable.")


class CollectionSheet(BranchScopedModel):
    STATUS_GENERATED = "generated"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_SUBMITTED = "submitted"
    STATUS_RECONCILED = "reconciled"
    STATUS_POSTED = "posted"
    STATUS_REVERSED = "reversed"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_GENERATED, "Generated"),
        (STATUS_IN_PROGRESS, "In progress"),
        (STATUS_SUBMITTED, "Submitted"),
        (STATUS_RECONCILED, "Reconciled"),
        (STATUS_POSTED, "Posted"),
        (STATUS_REVERSED, "Reversed"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    class Meta:
        db_table = "collection_sheets"
        ordering = ["-collection_date", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["center", "collection_date"],
                condition=~Q(status="cancelled"),
                name="uniq_active_collection_center_date",
            ),
            models.UniqueConstraint(
                fields=["generated_by", "idempotency_key"],
                name="uniq_collection_generator_key",
            ),
            models.CheckConstraint(
                condition=Q(cash_received__isnull=True) | Q(cash_received__gte=0),
                name="collection_cash_received_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(cash_shortage__gte=0) & Q(cash_excess__gte=0),
                name="collection_variance_nonnegative",
            ),
        ]
    objects = BranchScopedManager.from_queryset(CollectionSheetQuerySet)()
    unscoped = models.Manager.from_queryset(CollectionSheetQuerySet)()

    center = models.ForeignKey(
        "branch.Center", on_delete=models.PROTECT, related_name="collection_sheets"
    )
    group = models.ForeignKey(
        "branch.Group",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="collection_sheets",
    )
    field_officer = models.ForeignKey(
        "branch.Staff", on_delete=models.PROTECT, related_name="collection_sheets"
    )
    collection_date = models.DateField(db_index=True)
    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=STATUS_GENERATED, db_index=True
    )
    idempotency_key = models.UUIDField()
    posting_key = models.UUIDField(null=True, blank=True, unique=True)
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="collection_sheets_generated",
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="collection_sheets_submitted",
    )
    cash_received = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    cash_shortage = models.DecimalField(
        max_digits=18, decimal_places=2, default=Decimal("0.00")
    )
    cash_excess = models.DecimalField(
        max_digits=18, decimal_places=2, default=Decimal("0.00")
    )
    reconciled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="collection_sheets_reconciled",
    )
    reconciled_at = models.DateTimeField(null=True, blank=True)
    variance_journal = models.ForeignKey(
        "accounting.JournalEntry",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="collection_variances",
    )
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="collection_sheets_posted",
    )
    posted_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        errors = {}
        if self.center_id and self.center.branch_id != self.branch_id:
            errors["center"] = "The center must belong to this sheet's branch."
        if self.group_id and (
            self.group.branch_id != self.branch_id
            or self.group.center_id != self.center_id
        ):
            errors["group"] = "The group must belong to this center and branch."
        if self.field_officer_id and self.field_officer.branch_id != self.branch_id:
            errors["field_officer"] = "The field officer must belong to this branch."
        if self.status == self.STATUS_POSTED and (
            self.posted_at is None or self.posted_by_id is None
        ):
            errors["status"] = "A posted sheet requires posting details."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk:
            old_status = type(self).unscoped.filter(pk=self.pk).values_list(
                "status", flat=True
            ).first()
            if old_status == self.STATUS_REVERSED:
                raise TypeError("Reversed collection sheets are immutable.")
            if old_status == self.STATUS_POSTED and not getattr(
                self, "_reversal_authorized", False
            ):
                raise TypeError("Posted collection sheets are immutable.")
            if old_status and self.status != old_status:
                allowed = {
                    self.STATUS_GENERATED: {self.STATUS_IN_PROGRESS, self.STATUS_CANCELLED},
                    self.STATUS_IN_PROGRESS: {self.STATUS_SUBMITTED, self.STATUS_CANCELLED},
                    self.STATUS_SUBMITTED: {self.STATUS_RECONCILED},
                    self.STATUS_RECONCILED: {self.STATUS_POSTED},
                    self.STATUS_POSTED: {self.STATUS_REVERSED},
                }
                if self.status not in allowed.get(old_status, set()):
                    raise ValidationError("Invalid collection sheet status transition.")
        return super().save(*args, **kwargs)


class CollectionSheetItem(BranchScopedModel):
    class Meta:
        db_table = "collection_sheet_items"
        ordering = ["member__member_code"]
        constraints = [
            models.UniqueConstraint(
                fields=["sheet", "member"], name="uniq_collection_sheet_member"
            ),
            models.CheckConstraint(
                condition=(
                    Q(expected_installment__gte=0)
                    & Q(expected_overdue__gte=0)
                    & Q(expected_penalty__gte=0)
                    & Q(expected_savings__gte=0)
                    & Q(collected_amount__gte=0)
                    & Q(savings_amount__gte=0)
                ),
                name="collection_item_amounts_nonnegative",
            ),
        ]
    objects = BranchScopedManager.from_queryset(CollectionItemQuerySet)()
    unscoped = models.Manager.from_queryset(CollectionItemQuerySet)()

    sheet = models.ForeignKey(
        CollectionSheet, on_delete=models.PROTECT, related_name="items"
    )
    member = models.ForeignKey(
        "branch.Member", on_delete=models.PROTECT, related_name="collection_items"
    )
    expected_installment = models.DecimalField(
        max_digits=18, decimal_places=2, default=Decimal("0.00")
    )
    expected_overdue = models.DecimalField(
        max_digits=18, decimal_places=2, default=Decimal("0.00")
    )
    expected_penalty = models.DecimalField(
        max_digits=18, decimal_places=2, default=Decimal("0.00")
    )
    expected_savings = models.DecimalField(
        max_digits=18, decimal_places=2, default=Decimal("0.00")
    )
    collected_amount = models.DecimalField(
        max_digits=18, decimal_places=2, default=Decimal("0.00")
    )
    savings_amount = models.DecimalField(
        max_digits=18, decimal_places=2, default=Decimal("0.00")
    )
    reason = models.CharField(max_length=255, blank=True, default="")
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="collection_items_updated",
    )
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        from core.configuration.services import (
            get_business_rules,
            member_status_allowed,
        )

        if self.sheet_id and self.sheet.branch_id != self.branch_id:
            raise ValidationError({"branch": "The item must match its sheet branch."})
        if self.member_id and self.member.branch_id != self.branch_id:
            raise ValidationError({"member": "The member must belong to the sheet branch."})
        if (
            self.member_id
            and self.sheet_id
            and (
                self.member.center_id != self.sheet.center_id
                or (
                    self.sheet.group_id
                    and self.member.group_id != self.sheet.group_id
                )
            )
        ):
            raise ValidationError({"member": "The member must belong to the selected center or group."})
        if self.sheet_id and self.sheet.status in {
            CollectionSheet.STATUS_POSTED,
            CollectionSheet.STATUS_REVERSED,
        }:
            raise ValidationError("Posted collection rows are immutable.")
        if (
            self.collected_amount
            < self.expected_installment + self.expected_overdue + self.expected_penalty
            and not self.reason.strip()
            and get_business_rules().collection_rules.get(
                "require_short_collection_reason", True
            )
        ):
            raise ValidationError({"reason": "A reason is required when the loan collection is below the amount due."})
        if self.savings_amount and not member_status_allowed(
            "savings_deposit", self.member.status
        ):
            raise ValidationError({"savings_amount": "This member status cannot make savings deposits."})

    def save(self, *args, **kwargs):
        if self.sheet_id and CollectionSheet.unscoped.filter(
            pk=self.sheet_id,
            status__in=[
                CollectionSheet.STATUS_POSTED,
                CollectionSheet.STATUS_REVERSED,
            ],
        ).exists():
            raise TypeError("Rows on posted collection sheets are immutable.")
        return super().save(*args, **kwargs)


class CollectionPosting(models.Model):
    KIND_LOAN = "loan"
    KIND_SAVINGS = "savings"
    KIND_CHOICES = [(KIND_LOAN, "Loan repayment"), (KIND_SAVINGS, "Savings deposit")]

    class Meta:
        db_table = "collection_postings"
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(kind="loan", loan_payment__isnull=False, savings_transaction__isnull=True)
                    | Q(kind="savings", loan_payment__isnull=True, savings_transaction__isnull=False)
                ),
                name="collection_posting_source_matches_kind",
            ),
            models.UniqueConstraint(
                fields=["loan_payment"], condition=Q(loan_payment__isnull=False),
                name="uniq_collection_loan_payment",
            ),
            models.UniqueConstraint(
                fields=["savings_transaction"], condition=Q(savings_transaction__isnull=False),
                name="uniq_collection_savings_transaction",
            ),
            models.CheckConstraint(
                condition=Q(amount__gt=0),
                name="collection_posting_amount_positive",
            ),
        ]

    branch = models.ForeignKey("branch.Branch", on_delete=models.PROTECT)
    item = models.ForeignKey(
        CollectionSheetItem, on_delete=models.PROTECT, related_name="postings"
    )
    kind = models.CharField(max_length=12, choices=KIND_CHOICES)
    loan_payment = models.ForeignKey(
        "loans.LoanPayment", on_delete=models.PROTECT, null=True, blank=True
    )
    savings_transaction = models.ForeignKey(
        "savings.SavingsTransaction", on_delete=models.PROTECT, null=True, blank=True
    )
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        if self.item_id and self.item.branch_id != self.branch_id:
            raise ValidationError({"branch": "The posting must match its item branch."})
        if self.item_id and self.item.sheet.status in {
            CollectionSheet.STATUS_POSTED,
            CollectionSheet.STATUS_REVERSED,
        }:
            raise ValidationError("Postings on a posted collection sheet are immutable.")
        if self.loan_payment_id and self.loan_payment.branch_id != self.branch_id:
            raise ValidationError({"loan_payment": "The payment must belong to this posting branch."})
        if self.savings_transaction_id and self.savings_transaction.branch_id != self.branch_id:
            raise ValidationError({"savings_transaction": "The deposit must belong to this posting branch."})
        if self.amount is not None and self.amount <= 0:
            raise ValidationError({"amount": "A collection posting must be positive."})

    def save(self, *args, **kwargs):
        if self.pk:
            raise TypeError("Collection postings are immutable.")
        if self.item_id and CollectionSheet.unscoped.filter(
            pk=self.item.sheet_id,
            status__in=[
                CollectionSheet.STATUS_POSTED,
                CollectionSheet.STATUS_REVERSED,
            ],
        ).exists():
            raise TypeError("Postings on a posted collection sheet are immutable.")
        return super().save(*args, **kwargs)
    objects = models.Manager.from_queryset(CollectionPostingQuerySet)()


class CollectionSheetReversal(models.Model):
    STATUS_PENDING = "pending"
    STATUS_COMPLETED = "completed"
    class Meta:
        db_table = "collection_sheet_reversals"

    sheet = models.OneToOneField(
        CollectionSheet, on_delete=models.PROTECT, related_name="reversal_record"
    )
    reversal_date = models.DateField()
    idempotency_key = models.UUIDField(unique=True)
    reason = models.CharField(max_length=500)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="collection_reversals_requested",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.pk:
            raise TypeError("Collection sheet reversal records are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Collection sheet reversal records are immutable.")

    @property
    def status(self):
        return (
            self.STATUS_COMPLETED
            if CollectionSheetReversalApproval.objects.filter(reversal_id=self.pk).exists()
            else self.STATUS_PENDING
        )

    @property
    def approved_by_id(self):
        approval = CollectionSheetReversalApproval.objects.filter(
            reversal_id=self.pk
        ).values_list("approved_by_id", flat=True).first()
        return approval

    def get_status_display(self):
        return {
            self.STATUS_PENDING: "Pending approval",
            self.STATUS_COMPLETED: "Completed",
        }[self.status]


class CollectionSheetReversalApproval(models.Model):
    class Meta:
        db_table = "collection_sheet_reversal_approvals"

    reversal = models.OneToOneField(
        CollectionSheetReversal,
        on_delete=models.PROTECT,
        related_name="approval_record",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="collection_reversals_approved",
    )
    variance_journal_reversal = models.ForeignKey(
        "accounting.JournalEntry",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="collection_sheet_reversals",
    )
    completed_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.pk:
            raise TypeError("Collection reversal approvals are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Collection reversal approvals are immutable.")

class CollectionPostingReversal(models.Model):
    class Meta:
        db_table = "collection_posting_reversals"

    original_posting = models.OneToOneField(
        CollectionPosting, on_delete=models.PROTECT, related_name="reversal_record"
    )
    sheet_reversal = models.ForeignKey(
        CollectionSheetReversal,
        on_delete=models.PROTECT,
        related_name="posting_reversals",
    )
    loan_payment_reversal = models.ForeignKey(
        "loans.LoanPaymentReversal",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="collection_posting_reversals",
    )
    savings_transaction_reversal = models.ForeignKey(
        "savings.SavingsTransaction",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="collection_posting_reversals",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.pk:
            raise TypeError("Collection posting reversals are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Collection posting reversals are immutable.")
