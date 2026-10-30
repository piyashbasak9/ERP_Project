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


class JournalEntryQuerySet(BranchScopedQuerySet):
    def update(self, **kwargs):
        if kwargs.get('status') == 'posted':
            raise TypeError('Use JournalService to post entries.')
        if self.filter(status='posted').exists():
            raise TypeError('Posted journal entries are immutable; create a reversal instead.')
        return super().update(**kwargs)

    def delete(self):
        if self.filter(status='posted').exists():
            raise TypeError('Posted journal entries cannot be deleted; create a reversal instead.')
        return super().delete()


class JournalLineQuerySet(models.QuerySet):
    def update(self, **kwargs):
        if self.filter(entry__status='posted').exists():
            raise TypeError('Lines on posted journal entries are immutable.')
        return super().update(**kwargs)

    def delete(self):
        if self.filter(entry__status='posted').exists():
            raise TypeError('Lines on posted journal entries cannot be deleted.')
        return super().delete()


class AccountReconciliationQuerySet(models.QuerySet):
    def update(self, **kwargs):
        if kwargs.get('status') == 'reconciled' or self.filter(status='reconciled').exists():
            raise TypeError('Confirmed reconciliations are immutable.')
        return super().update(**kwargs)

    def delete(self):
        if self.filter(status='reconciled').exists():
            raise TypeError('Confirmed reconciliations cannot be deleted.')
        return super().delete()


class Account(models.Model):
    ASSET = 'asset'
    LIABILITY = 'liability'
    EQUITY = 'equity'
    INCOME = 'income'
    EXPENSE = 'expense'
    ACCOUNT_TYPE_CHOICES = [
        (ASSET, 'Asset'),
        (LIABILITY, 'Liability'),
        (EQUITY, 'Equity'),
        (INCOME, 'Income'),
        (EXPENSE, 'Expense'),
    ]
    DEBIT = 'debit'
    CREDIT = 'credit'
    NORMAL_BALANCE_CHOICES = [(DEBIT, 'Debit'), (CREDIT, 'Credit')]

    class Meta:
        db_table = 'accounting_accounts'
        ordering = ['code']

    code = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=150)
    parent = models.ForeignKey(
        'self',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='children',
    )
    account_type = models.CharField(max_length=20, choices=ACCOUNT_TYPE_CHOICES)
    normal_balance = models.CharField(max_length=10, choices=NORMAL_BALANCE_CHOICES)
    allows_direct_posting = models.BooleanField(default=True)
    is_system = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True, db_index=True)

    def clean(self):
        if self.pk and self.parent_id == self.pk:
            raise ValidationError({'parent': 'An account cannot be its own parent.'})
        if self.parent_id and self.parent.account_type != self.account_type:
            raise ValidationError({'parent': 'Parent and child accounts must have the same account type.'})
        if self.pk and self.parent_id:
            ancestor = self.parent
            while ancestor:
                if ancestor.pk == self.pk:
                    raise ValidationError({'parent': 'An account hierarchy cannot contain a cycle.'})
                ancestor = ancestor.parent

    def __str__(self):
        return f'{self.code} — {self.name}'


class FiscalYear(models.Model):
    class Meta:
        db_table = 'accounting_fiscal_years'
        ordering = ['-start_date']

    name = models.CharField(max_length=80, unique=True)
    start_date = models.DateField()
    end_date = models.DateField()
    is_closed = models.BooleanField(default=False, db_index=True)

    def clean(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError({'end_date': 'The end date must be on or after the start date.'})
        if self.start_date and self.end_date:
            overlaps = FiscalYear.objects.filter(
                start_date__lte=self.end_date,
                end_date__gte=self.start_date,
            )
            if self.pk:
                overlaps = overlaps.exclude(pk=self.pk)
            if overlaps.exists():
                raise ValidationError('Fiscal years cannot overlap.')

    def __str__(self):
        return self.name


class AccountingPeriod(models.Model):
    class Meta:
        db_table = 'accounting_periods'
        ordering = ['fiscal_year', 'start_date']
        constraints = [
            models.UniqueConstraint(
                fields=['fiscal_year', 'number'],
                name='uniq_accounting_period_number',
            ),
        ]

    fiscal_year = models.ForeignKey(FiscalYear, on_delete=models.PROTECT, related_name='periods')
    number = models.PositiveSmallIntegerField()
    name = models.CharField(max_length=40)
    start_date = models.DateField()
    end_date = models.DateField()
    is_closed = models.BooleanField(default=False, db_index=True)

    def clean(self):
        errors = {}
        if self.number is not None and not 1 <= self.number <= 12:
            errors['number'] = 'Accounting period numbers must be from 1 through 12.'
        if self.start_date and self.end_date and self.end_date < self.start_date:
            errors['end_date'] = 'The end date must be on or after the start date.'
        if self.fiscal_year_id and self.start_date and self.end_date and (
            self.start_date < self.fiscal_year.start_date
            or self.end_date > self.fiscal_year.end_date
        ):
            errors['fiscal_year'] = 'The period must be within its fiscal year.'
        if self.fiscal_year_id and self.start_date and self.end_date:
            overlaps = AccountingPeriod.objects.filter(
                fiscal_year_id=self.fiscal_year_id,
                start_date__lte=self.end_date,
                end_date__gte=self.start_date,
            )
            if self.pk:
                overlaps = overlaps.exclude(pk=self.pk)
            if overlaps.exists():
                errors['start_date'] = 'Accounting periods cannot overlap.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f'{self.fiscal_year.name} — {self.name}'


class SystemAccountMapping(models.Model):
    SYSTEM_ACCOUNT_KEYS = [
        ('cash_in_hand', 'Cash in Hand'),
        ('bank_accounts', 'Bank Accounts'),
        ('loans_to_members', 'Loans to Members'),
        ('loan_loss_provision', 'Loan Loss Provision'),
        ('member_savings', 'Member Savings'),
        ('interest_income', 'Interest Income'),
        ('interest_expense', 'Interest Expense on Savings'),
        ('fee_income', 'Fee Income'),
        ('insurance_income', 'Insurance Fee Income'),
        ('penalty_income', 'Penalty Income'),
        ('loan_overpayment_payable', 'Loan Overpayment Payable'),
        ('recovery_income', 'Recovery of Written-off Loans'),
        ('withholding_tax_payable', 'Withholding Tax Payable'),
    ]
    EXPECTED_ACCOUNT_TYPES = {
        'cash_in_hand': Account.ASSET,
        'bank_accounts': Account.ASSET,
        'loans_to_members': Account.ASSET,
        'loan_loss_provision': Account.ASSET,
        'member_savings': Account.LIABILITY,
        'interest_income': Account.INCOME,
        'interest_expense': Account.EXPENSE,
        'fee_income': Account.INCOME,
        'insurance_income': Account.INCOME,
        'penalty_income': Account.INCOME,
        'loan_overpayment_payable': Account.LIABILITY,
        'recovery_income': Account.INCOME,
        'withholding_tax_payable': Account.LIABILITY,
    }

    class Meta:
        db_table = 'accounting_system_account_mappings'

    key = models.CharField(max_length=60, choices=SYSTEM_ACCOUNT_KEYS, unique=True)
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name='system_mappings')

    def clean(self):
        if self.account_id and not self.account.is_active:
            raise ValidationError({'account': 'A system account mapping must point to an active account.'})
        if self.account_id and not self.account.allows_direct_posting:
            raise ValidationError({'account': 'A system account mapping must point to a postable account.'})
        expected_type = self.EXPECTED_ACCOUNT_TYPES.get(self.key)
        if self.account_id and expected_type and self.account.account_type != expected_type:
            raise ValidationError({'account': f'This mapping requires an {expected_type} account.'})


class VoucherSequence(BranchScopedModel):
    VOUCHER_JOURNAL = 'journal'
    VOUCHER_CASH = 'cash'
    VOUCHER_BANK = 'bank'
    VOUCHER_SYSTEM = 'system'
    VOUCHER_TYPE_CHOICES = [
        (VOUCHER_JOURNAL, 'Journal'),
        (VOUCHER_CASH, 'Cash'),
        (VOUCHER_BANK, 'Bank'),
        (VOUCHER_SYSTEM, 'System'),
    ]

    class Meta:
        db_table = 'accounting_voucher_sequences'
        constraints = [
            models.UniqueConstraint(
                fields=['branch', 'fiscal_year', 'voucher_type'],
                name='uniq_voucher_sequence_scope',
            ),
        ]

    fiscal_year = models.ForeignKey(FiscalYear, on_delete=models.PROTECT, related_name='voucher_sequences')
    voucher_type = models.CharField(max_length=20, choices=VOUCHER_TYPE_CHOICES)
    next_number = models.PositiveBigIntegerField(default=1)


class JournalEntry(BranchScopedModel):
    STATUS_DRAFT = 'draft'
    STATUS_PENDING = 'pending_approval'
    STATUS_POSTED = 'posted'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'),
        (STATUS_PENDING, 'Pending approval'),
        (STATUS_POSTED, 'Posted'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    class Meta:
        db_table = 'accounting_journal_entries'
        ordering = ['-journal_date', '-pk']
        constraints = [
            models.UniqueConstraint(
                fields=['branch', 'fiscal_year', 'voucher_type', 'voucher_number'],
                name='uniq_journal_voucher_number',
            ),
            models.UniqueConstraint(
                fields=['created_by', 'idempotency_key'],
                name='uniq_journal_idempotency_key',
            ),
        ]
        indexes = [
            models.Index(fields=['branch', 'journal_date', 'status'], name='journal_branch_date_idx'),
        ]

    objects = BranchScopedManager.from_queryset(JournalEntryQuerySet)()
    unscoped = models.Manager.from_queryset(JournalEntryQuerySet)()

    fiscal_year = models.ForeignKey(FiscalYear, on_delete=models.PROTECT, related_name='journal_entries')
    period = models.ForeignKey(AccountingPeriod, on_delete=models.PROTECT, related_name='journal_entries')
    voucher_type = models.CharField(max_length=20, choices=VoucherSequence.VOUCHER_TYPE_CHOICES)
    voucher_number = models.CharField(max_length=40)
    journal_date = models.DateField(db_index=True)
    narration = models.CharField(max_length=500)
    idempotency_key = models.UUIDField(default=uuid.uuid4, editable=False)
    source_type = models.CharField(max_length=80, blank=True, default='')
    source_id = models.CharField(max_length=100, blank=True, default='')
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default=STATUS_DRAFT, db_index=True)
    requires_approval = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='journal_entries_created',
    )
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='journal_entries_posted',
    )
    posted_at = models.DateTimeField(null=True, blank=True)
    reversal_of = models.OneToOneField(
        'self',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='reversal_entry',
    )

    def clean(self):
        if self.fiscal_year_id and self.journal_date and not (
            self.fiscal_year.start_date <= self.journal_date <= self.fiscal_year.end_date
        ):
            raise ValidationError({'journal_date': 'The journal date must be inside the fiscal year.'})
        if self.period_id and self.journal_date and (
            self.period.fiscal_year_id != self.fiscal_year_id
            or not self.period.start_date <= self.journal_date <= self.period.end_date
        ):
            raise ValidationError({'period': 'The journal date must be inside the selected period.'})

    def save(self, *args, **kwargs):
        if self.pk:
            original_status = type(self).unscoped.filter(pk=self.pk).values_list('status', flat=True).first()
            if original_status == self.STATUS_POSTED:
                raise TypeError('Posted journal entries are immutable; create a reversal instead.')
            if (
                self.status == self.STATUS_POSTED
                and not getattr(self, '_posting_authorized', False)
            ):
                raise TypeError('Use JournalService to post entries.')
        elif self.status == self.STATUS_POSTED:
            raise TypeError('Use JournalService to post entries.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.pk and type(self).unscoped.filter(pk=self.pk, status=self.STATUS_POSTED).exists():
            raise TypeError('Posted journal entries cannot be deleted; create a reversal instead.')
        return super().delete(*args, **kwargs)

    def __str__(self):
        return self.voucher_number


class JournalLine(models.Model):
    class Meta:
        db_table = 'accounting_journal_lines'
        ordering = ['pk']
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(debit__gt=Decimal(0), credit=Decimal(0))
                    | Q(credit__gt=Decimal(0), debit=Decimal(0))
                ),
                name='journal_line_one_positive_side',
            ),
        ]
        indexes = [models.Index(fields=['account', 'entry'], name='journal_line_account_idx')]

    objects = models.Manager.from_queryset(JournalLineQuerySet)()

    entry = models.ForeignKey(JournalEntry, on_delete=models.PROTECT, related_name='lines')
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name='journal_lines')
    debit = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('0.00'))
    credit = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('0.00'))
    narration = models.CharField(max_length=255, blank=True, default='')

    def clean(self):
        if (self.debit > 0) == (self.credit > 0):
            raise ValidationError('A journal line must have either a debit or a credit, but not both.')
        if self.debit < 0 or self.credit < 0:
            raise ValidationError('Journal amounts cannot be negative.')
        if self.account_id and (
            not self.account.is_active or not self.account.allows_direct_posting
        ):
            raise ValidationError({'account': 'Select an active account that allows direct posting.'})

    def save(self, *args, **kwargs):
        if self.entry_id and JournalEntry.unscoped.filter(
            pk=self.entry_id,
            status=JournalEntry.STATUS_POSTED,
        ).exists():
            raise TypeError('Lines on posted journal entries are immutable.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if JournalEntry.unscoped.filter(
            pk=self.entry_id,
            status=JournalEntry.STATUS_POSTED,
        ).exists():
            raise TypeError('Lines on posted journal entries cannot be deleted.')
        return super().delete(*args, **kwargs)


class AccountReconciliation(models.Model):
    STATUS_OPEN = 'open'
    STATUS_RECONCILED = 'reconciled'
    STATUS_CHOICES = [
        (STATUS_OPEN, 'Open'),
        (STATUS_RECONCILED, 'Reconciled'),
    ]

    class Meta:
        db_table = 'accounting_reconciliations'
        ordering = ['-as_of_date', 'account__code']
        constraints = [
            models.UniqueConstraint(
                fields=['branch', 'account', 'as_of_date'],
                name='uniq_account_reconciliation_date',
            ),
            models.CheckConstraint(
                condition=Q(statement_balance__gte=Decimal(0)),
                name='reconciliation_statement_nonnegative',
            ),
        ]

    objects = models.Manager.from_queryset(AccountReconciliationQuerySet)()

    branch = models.ForeignKey('branch.Branch', on_delete=models.PROTECT, related_name='account_reconciliations')
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name='reconciliations')
    as_of_date = models.DateField()
    statement_balance = models.DecimalField(max_digits=18, decimal_places=2)
    book_balance = models.DecimalField(max_digits=18, decimal_places=2)
    variance = models.DecimalField(max_digits=18, decimal_places=2)
    notes = models.CharField(max_length=500, blank=True, default='')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_OPEN, db_index=True)
    prepared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='account_reconciliations_prepared',
    )
    reconciled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='account_reconciliations_confirmed',
    )
    reconciled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        if self.account_id and self.account.account_type != Account.ASSET:
            raise ValidationError({'account': 'Only asset accounts can be reconciled against cash or bank balances.'})
        if self.statement_balance is not None and self.statement_balance < 0:
            raise ValidationError({'statement_balance': 'Statement balance cannot be negative.'})
        if (
            self.variance is not None
            and self.statement_balance is not None
            and self.book_balance is not None
            and self.variance != self.statement_balance - self.book_balance
        ):
            raise ValidationError({'variance': 'Variance must equal statement balance minus book balance.'})

    def save(self, *args, **kwargs):
        if self.pk:
            original_status = type(self).objects.filter(pk=self.pk).values_list('status', flat=True).first()
            if original_status == self.STATUS_RECONCILED:
                raise TypeError('Confirmed reconciliations are immutable.')
        if (
            self.status == self.STATUS_RECONCILED
            and not getattr(self, '_reconciliation_authorized', False)
        ):
            raise TypeError('Use the reconciliation service to confirm records.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk, status=self.STATUS_RECONCILED).exists():
            raise TypeError('Confirmed reconciliations cannot be deleted.')
        return super().delete(*args, **kwargs)
