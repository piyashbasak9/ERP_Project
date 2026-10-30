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


class SavingsProduct(models.Model):
    TYPE_GENERAL = 'general'
    TYPE_COMPULSORY = 'compulsory'
    TYPE_CHOICES = [
        (TYPE_GENERAL, 'General'),
        (TYPE_COMPULSORY, 'Compulsory'),
    ]
    METHOD_DAILY_BALANCE = 'daily_balance'
    METHOD_MINIMUM_BALANCE = 'minimum_balance'
    INTEREST_METHOD_CHOICES = [
        (METHOD_DAILY_BALANCE, 'Daily balance'),
        (METHOD_MINIMUM_BALANCE, 'Minimum balance'),
    ]
    FREQUENCY_MONTHLY = 'monthly'
    FREQUENCY_QUARTERLY = 'quarterly'
    FREQUENCY_HALF_YEARLY = 'half_yearly'
    FREQUENCY_YEARLY = 'yearly'
    FREQUENCY_CHOICES = [
        (FREQUENCY_MONTHLY, 'Monthly'),
        (FREQUENCY_QUARTERLY, 'Quarterly'),
        (FREQUENCY_HALF_YEARLY, 'Half-yearly'),
        (FREQUENCY_YEARLY, 'Yearly'),
    ]

    class Meta:
        db_table = 'savings_products'
        ordering = ['code']
        constraints = [
            models.CheckConstraint(
                condition=Q(dormant_after_days__isnull=True) | Q(dormant_after_days__gte=1),
                name='savings_dormancy_days_positive',
            ),
        ]

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=120)
    savings_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    annual_interest_rate = models.DecimalField(max_digits=7, decimal_places=6, default=Decimal(0))
    interest_method = models.CharField(
        max_length=24,
        choices=INTEREST_METHOD_CHOICES,
        default=METHOD_DAILY_BALANCE,
    )
    posting_frequency = models.CharField(
        max_length=20,
        choices=FREQUENCY_CHOICES,
        default=FREQUENCY_MONTHLY,
    )
    minimum_opening_balance = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('0.00'))
    minimum_balance = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('0.00'))
    dormant_after_days = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text='Days without a posted savings transaction before an account becomes dormant.',
    )
    pays_interest_when_dormant = models.BooleanField(default=False)
    fee_amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('0.00'))
    maximum_withdrawal = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    withdrawal_approval_threshold = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
    )
    withholding_tax_rate = models.DecimalField(max_digits=7, decimal_places=6, default=Decimal(0))
    allow_withdrawals = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True, db_index=True)

    def clean(self):
        errors = {}
        if self.annual_interest_rate is not None and (
            self.annual_interest_rate < 0 or self.annual_interest_rate > 1
        ):
            errors['annual_interest_rate'] = 'Enter an annual rate as a decimal from 0 through 1.'
        if self.withholding_tax_rate is not None and (
            self.withholding_tax_rate < 0 or self.withholding_tax_rate > 1
        ):
            errors['withholding_tax_rate'] = 'Enter a tax rate as a decimal from 0 through 1.'
        if self.minimum_opening_balance < 0 or self.minimum_balance < 0:
            errors['minimum_balance'] = 'Opening and minimum balances cannot be negative.'
        if self.fee_amount < 0:
            errors['fee_amount'] = 'Fees cannot be negative.'
        if self.dormant_after_days is not None and self.dormant_after_days < 1:
            errors['dormant_after_days'] = 'Dormancy must be configured for at least one inactive day.'
        if self.maximum_withdrawal is not None and self.maximum_withdrawal <= 0:
            errors['maximum_withdrawal'] = 'Maximum withdrawal must be greater than zero.'
        if (
            self.withdrawal_approval_threshold is not None
            and self.withdrawal_approval_threshold < 0
        ):
            errors['withdrawal_approval_threshold'] = 'Approval threshold cannot be negative.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f'{self.code} — {self.name}'

    def snapshot_terms(self):
        names = (
            'code',
            'name',
            'savings_type',
            'annual_interest_rate',
            'interest_method',
            'posting_frequency',
            'minimum_opening_balance',
            'minimum_balance',
            'dormant_after_days',
            'pays_interest_when_dormant',
            'fee_amount',
            'maximum_withdrawal',
            'withdrawal_approval_threshold',
            'withholding_tax_rate',
            'allow_withdrawals',
        )
        return {
            name: (
                str(getattr(self, name))
                if isinstance(getattr(self, name), Decimal)
                else getattr(self, name)
            )
            for name in names
        }


class SavingsAccountQuerySet(BranchScopedQuerySet):
    protected_fields = {
        'account_number',
        'branch',
        'branch_id',
        'product',
        'product_id',
        'member',
        'member_id',
        'group',
        'group_id',
        'status',
        'balance',
        'reserved_balance',
        'opened_at',
        'closed_at',
        'version',
        'idempotency_key',
        'created_by',
        'created_by_id',
    }
    protected_attnames = {
        'account_number',
        'branch_id',
        'product_id',
        'member_id',
        'group_id',
        'status',
        'balance',
        'reserved_balance',
        'opened_at',
        'closed_at',
        'version',
        'idempotency_key',
        'created_by_id',
    }

    def update(self, **kwargs):
        if self.protected_fields.intersection(kwargs):
            raise TypeError('Use SavingsService to change savings account ownership or balances.')
        return super().update(**kwargs)

    def delete(self):
        raise TypeError('Savings accounts are permanent financial records.')


class SavingsAccount(BranchScopedModel):
    STATUS_PENDING = 'pending'
    STATUS_ACTIVE = 'active'
    STATUS_DORMANT = 'dormant'
    STATUS_CLOSED = 'closed'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_ACTIVE, 'Active'),
        (STATUS_DORMANT, 'Dormant'),
        (STATUS_CLOSED, 'Closed'),
    ]

    class Meta:
        db_table = 'savings_accounts'
        ordering = ['account_number']
        constraints = [
            models.CheckConstraint(
                condition=Q(balance__gte=Decimal(0)),
                name='savings_account_balance_nonnegative',
            ),
            models.CheckConstraint(
                condition=Q(reserved_balance__gte=Decimal(0)),
                name='savings_account_reserved_nonnegative',
            ),
            models.CheckConstraint(
                condition=Q(reserved_balance__lte=models.F('balance')),
                name='savings_account_reservation_within_balance',
            ),
            models.CheckConstraint(
                condition=~Q(status='closed') | Q(balance=Decimal('0.00')),
                name='closed_savings_account_zero_balance',
            ),
            models.UniqueConstraint(
                fields=['created_by', 'idempotency_key'],
                name='uniq_savings_open_idempotency',
            ),
        ]

    objects = BranchScopedManager.from_queryset(SavingsAccountQuerySet)()
    unscoped = models.Manager.from_queryset(SavingsAccountQuerySet)()

    product = models.ForeignKey(SavingsProduct, on_delete=models.PROTECT, related_name='accounts')
    terms_snapshot = models.JSONField(default=dict, blank=True)
    member = models.ForeignKey(
        'branch.Member',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='savings_accounts',
    )
    group = models.ForeignKey(
        'branch.Group',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='savings_accounts',
    )
    account_number = models.CharField(max_length=64, unique=True)
    idempotency_key = models.UUIDField(default=uuid.uuid4, editable=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    balance = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('0.00'))
    reserved_balance = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('0.00'))
    opened_at = models.DateField()
    closed_at = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='savings_accounts_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        if bool(self.member_id) == bool(self.group_id):
            raise ValidationError('A savings account must belong to exactly one member or group.')
        if self.member_id and self.member.branch_id != self.branch_id:
            raise ValidationError({'member': 'The member must belong to the savings account branch.'})
        if self.group_id and self.group.branch_id != self.branch_id:
            raise ValidationError({'group': 'The group must belong to the savings account branch.'})
        if self.balance < 0 or self.reserved_balance < 0:
            raise ValidationError('Savings balances cannot be negative.')
        if self.reserved_balance > self.balance:
            raise ValidationError({'reserved_balance': 'Reserved funds cannot exceed the account balance.'})
        if self.status == self.STATUS_CLOSED and self.balance != 0:
            raise ValidationError({'status': 'An account can be closed only when its balance is zero.'})

    def save(self, *args, **kwargs):
        authorized = getattr(self, '_savings_update_authorized', False)
        if not self.pk and not authorized:
            raise TypeError('Use SavingsService to open a savings account.')
        if self.pk:
            original = type(self).unscoped.filter(pk=self.pk).values(
                *SavingsAccountQuerySet.protected_attnames
            ).first()
            if original is not None and not authorized and any(
                original[field] != getattr(self, field)
                for field in SavingsAccountQuerySet.protected_attnames
            ):
                raise TypeError('Use SavingsService to change savings account ownership or balances.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError('Savings accounts are permanent financial records.')

    @property
    def available_balance(self):
        return self.balance - self.reserved_balance

    def product_term(self, name):
        value = self.terms_snapshot.get(name)
        if value is None and name not in self.terms_snapshot:
            value = getattr(self.product, name)
        if isinstance(self.product._meta.get_field(name), models.DecimalField):
            return Decimal(value) if value is not None else None
        return value

    def __str__(self):
        return self.account_number


class SavingsAccountSequence(models.Model):
    class Meta:
        db_table = 'savings_account_sequences'
        constraints = [
            models.UniqueConstraint(
                fields=['branch', 'product'],
                name='uniq_savings_account_sequence',
            ),
        ]

    branch = models.ForeignKey('branch.Branch', on_delete=models.PROTECT)
    product = models.ForeignKey(SavingsProduct, on_delete=models.PROTECT)
    next_number = models.PositiveBigIntegerField(default=1)


class SavingsTransactionQuerySet(BranchScopedQuerySet):
    FINAL_STATUSES = {'posted', 'rejected'}

    def update(self, **kwargs):
        if kwargs.get('status') in self.FINAL_STATUSES or self.filter(
            status__in=self.FINAL_STATUSES
        ).exists():
            raise TypeError('Posted or rejected savings transactions are immutable.')
        return super().update(**kwargs)

    def delete(self):
        raise TypeError('Savings transaction records cannot be deleted.')


class SavingsTransaction(BranchScopedModel):
    TYPE_DEPOSIT = 'deposit'
    TYPE_WITHDRAWAL = 'withdrawal'
    TYPE_INTEREST = 'interest'
    TYPE_FEE = 'fee'
    TYPE_REVERSAL = 'reversal'
    TYPE_CHOICES = [
        (TYPE_DEPOSIT, 'Deposit'),
        (TYPE_WITHDRAWAL, 'Withdrawal'),
        (TYPE_INTEREST, 'Interest'),
        (TYPE_FEE, 'Fee'),
        (TYPE_REVERSAL, 'Reversal'),
    ]
    STATUS_PENDING = 'pending'
    STATUS_POSTED = 'posted'
    STATUS_REJECTED = 'rejected'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending approval'),
        (STATUS_POSTED, 'Posted'),
        (STATUS_REJECTED, 'Rejected'),
    ]
    CHANNEL_CASH = 'cash'
    CHANNEL_BANK = 'bank'
    CHANNEL_CHOICES = [(CHANNEL_CASH, 'Cash'), (CHANNEL_BANK, 'Bank')]

    class Meta:
        db_table = 'savings_transactions'
        ordering = ['-transaction_date', '-pk']
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gt=Decimal(0)),
                name='savings_transaction_amount_positive',
            ),
            models.CheckConstraint(
                condition=Q(balance_before__gte=Decimal(0)) & Q(balance_after__gte=Decimal(0)),
                name='savings_transaction_balances_nonnegative',
            ),
            models.UniqueConstraint(
                fields=['created_by', 'idempotency_key'],
                name='uniq_savings_idempotency_key',
            ),
            models.UniqueConstraint(
                fields=['account', 'period_start', 'period_end'],
                condition=Q(transaction_type='interest', status='posted'),
                name='uniq_savings_interest_period',
            ),
        ]
        indexes = [
            models.Index(fields=['account', 'transaction_date', 'status'], name='savings_tx_account_date_idx'),
        ]

    objects = BranchScopedManager.from_queryset(SavingsTransactionQuerySet)()
    unscoped = models.Manager.from_queryset(SavingsTransactionQuerySet)()

    account = models.ForeignKey(SavingsAccount, on_delete=models.PROTECT, related_name='transactions')
    transaction_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_POSTED, db_index=True)
    transaction_date = models.DateField(db_index=True)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    gross_amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('0.00'))
    tax_amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('0.00'))
    period_start = models.DateField(null=True, blank=True)
    period_end = models.DateField(null=True, blank=True)
    balance_before = models.DecimalField(max_digits=18, decimal_places=2)
    balance_after = models.DecimalField(max_digits=18, decimal_places=2)
    payment_channel = models.CharField(max_length=10, choices=CHANNEL_CHOICES, default=CHANNEL_CASH)
    contribution_member = models.ForeignKey(
        'branch.Member',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='group_savings_contributions',
    )
    journal_entry = models.OneToOneField(
        'accounting.JournalEntry',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='savings_transaction',
    )
    reversal_of = models.OneToOneField(
        'self',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='reversal_transaction',
    )
    idempotency_key = models.UUIDField(default=uuid.uuid4, editable=False)
    narration = models.CharField(max_length=255, blank=True, default='')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='savings_transactions_created',
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='savings_transactions_approved',
    )
    rejected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='savings_transactions_rejected',
    )
    rejection_reason = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        if self.amount is not None and self.amount <= 0:
            raise ValidationError({'amount': 'Transaction amount must be greater than zero.'})
        if self.gross_amount < 0 or self.tax_amount < 0:
            raise ValidationError('Interest and tax amounts cannot be negative.')
        if self.balance_before is not None and self.balance_before < 0:
            raise ValidationError({'balance_before': 'Transaction balances cannot be negative.'})
        if self.balance_after is not None and self.balance_after < 0:
            raise ValidationError({'balance_after': 'Transaction balances cannot be negative.'})
        if self.status == self.STATUS_POSTED and self.journal_entry_id is None:
            raise ValidationError({'journal_entry': 'A posted savings transaction requires a journal entry.'})
        if self.account_id and self.branch_id != self.account.branch_id:
            raise ValidationError({'branch': 'The transaction branch must match its savings account.'})
        if self.journal_entry_id and self.branch_id != self.journal_entry.branch_id:
            raise ValidationError({'journal_entry': 'The journal entry must belong to the transaction branch.'})
        if (
            self.account_id
            and self.contribution_member_id
            and (
                not self.account.group_id
                or self.contribution_member.group_id != self.account.group_id
                or self.contribution_member.branch_id != self.branch_id
            )
        ):
            raise ValidationError({
                'contribution_member': 'A group contribution must name a member of this account group.'
            })
        if self.status == self.STATUS_PENDING and self.transaction_type != self.TYPE_WITHDRAWAL:
            raise ValidationError('Only withdrawals can await approval.')
        if self.status == self.STATUS_REJECTED and self.transaction_type != self.TYPE_WITHDRAWAL:
            raise ValidationError('Only withdrawals can be rejected.')
        if self.status == self.STATUS_POSTED and self.transaction_type == self.TYPE_INTEREST:
            if self.gross_amount != self.amount + self.tax_amount:
                raise ValidationError('Gross interest must equal posted interest plus withholding tax.')
            if not self.period_start or not self.period_end or self.period_end < self.period_start:
                raise ValidationError({'period_start': 'A valid interest period is required.'})
        if self.status == self.STATUS_POSTED and self.transaction_type == self.TYPE_REVERSAL:
            if not self.reversal_of_id:
                raise ValidationError({'reversal_of': 'A reversal must reference its original transaction.'})
            original_change = self.reversal_of.balance_after - self.reversal_of.balance_before
            if self.balance_after - self.balance_before != -original_change:
                raise ValidationError('A reversal must offset the original savings balance change.')
        elif self.status == self.STATUS_POSTED and self.transaction_type in {
            self.TYPE_DEPOSIT,
            self.TYPE_INTEREST,
        } and self.balance_after - self.balance_before != self.amount:
            raise ValidationError('A deposit or interest posting must increase the savings balance by its amount.')
        elif self.status == self.STATUS_POSTED and self.transaction_type in {
            self.TYPE_WITHDRAWAL,
            self.TYPE_FEE,
        } and self.balance_before - self.balance_after != self.amount:
            raise ValidationError('A withdrawal or fee must reduce the savings balance by its amount.')

    def save(self, *args, **kwargs):
        if self.pk:
            original_status = type(self).unscoped.filter(pk=self.pk).values_list('status', flat=True).first()
            if original_status in {self.STATUS_POSTED, self.STATUS_REJECTED}:
                raise TypeError('Posted or rejected savings transactions are immutable.')
        if (
            self.status == self.STATUS_POSTED
            and not getattr(self, '_posting_authorized', False)
        ):
            raise TypeError('Use SavingsService to post transactions.')
        if (
            self.status == self.STATUS_REJECTED
            and not getattr(self, '_rejection_authorized', False)
        ):
            raise TypeError('Use SavingsService to reject transactions.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError('Savings transaction records cannot be deleted.')

    def __str__(self):
        return f'{self.account.account_number} — {self.get_transaction_type_display()}'
