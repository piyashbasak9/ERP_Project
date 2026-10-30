import uuid
from calendar import monthrange
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import OuterRef, Subquery, Sum
from django.utils import timezone

from core.accounting.models import (
    JournalEntry,
    SystemAccountMapping,
    VoucherSequence,
)
from core.accounting.services import ZERO, JournalService
from core.audit.services import log_action
from core.branch.models import Branch, Group, Member

from .models import (
    SavingsAccount,
    SavingsAccountSequence,
    SavingsProduct,
    SavingsTransaction,
)

CENT = Decimal('0.01')
YEAR_DAYS = Decimal(365)
MAX_MONEY = Decimal('9999999999999999.99')


class SavingsService:
    def __init__(self, request):
        self.request = request

    @transaction.atomic
    def open_account(
        self,
        *,
        branch_id,
        product_id,
        opened_at,
        member_id=None,
        group_id=None,
        opening_balance=ZERO,
        contribution_member_id=None,
        idempotency_key=None,
    ):
        user = self._active_user()
        key = self._uuid_key(idempotency_key)
        self._ensure_branch_access(branch_id)
        existing = SavingsAccount.unscoped.filter(
            created_by=user,
            idempotency_key=key,
        ).first()
        if existing:
            if existing.branch_id != branch_id:
                raise ValidationError({'idempotency_key': 'This key was already used for another branch.'})
            opening_transaction = SavingsTransaction.unscoped.filter(
                account=existing,
                transaction_type=SavingsTransaction.TYPE_DEPOSIT,
                narration='Opening deposit',
            ).first()
            if (
                existing.product_id != product_id
                or existing.member_id != member_id
                or existing.group_id != group_id
                or existing.opened_at != opened_at
                or (opening_transaction.amount if opening_transaction else ZERO) != opening_balance
            ):
                raise ValidationError({
                    'idempotency_key': 'This key was already used with different account details.'
                })
            existing._idempotent_replay = True
            return existing
        branch = Branch.unscoped.select_for_update().filter(pk=branch_id, is_active=True).first()
        if branch is None:
            raise ValidationError({'branch': 'The selected branch is not active.'})
        product = SavingsProduct.objects.select_for_update().filter(
            pk=product_id,
            is_active=True,
        ).first()
        if product is None:
            raise ValidationError({'product': 'Select an active savings product.'})
        self._validate_money(opening_balance, allow_zero=True, field='opening_balance')
        if opening_balance < product.minimum_opening_balance:
            raise ValidationError({
                'opening_balance': f'The minimum opening balance is {product.minimum_opening_balance}.'
            })

        member = None
        group = None
        if member_id is not None:
            member = Member.unscoped.filter(pk=member_id, branch_id=branch_id).first()
            if member is None or member.status != Member.STATUS_ACTIVE:
                raise ValidationError({'member': 'Select an active member in this branch.'})
        elif group_id is not None:
            group = Group.unscoped.filter(pk=group_id, branch_id=branch_id, is_active=True).first()
            if group is None:
                raise ValidationError({'group': 'Select an active group in this branch.'})
        else:
            raise ValidationError('Select either one member or one group for the savings account.')

        sequence, _ = SavingsAccountSequence.objects.get_or_create(
            branch=branch,
            product=product,
            defaults={'next_number': 1},
        )
        sequence = SavingsAccountSequence.objects.select_for_update().get(pk=sequence.pk)
        account_number = (
            f'{branch.code}-{product.code}-{sequence.next_number:06d}'
        )
        sequence.next_number += 1
        sequence.save(update_fields=['next_number'])

        account = SavingsAccount(
            branch=branch,
            product=product,
            terms_snapshot=product.snapshot_terms(),
            member=member,
            group=group,
            account_number=account_number,
            idempotency_key=key,
            status=SavingsAccount.STATUS_ACTIVE,
            balance=ZERO,
            opened_at=opened_at,
            created_by=user,
        )
        account.full_clean()
        self._save_account(account)
        log_action(
            'Open',
            'SavingsAccount',
            account.pk,
            new_values={
                'account_number': account.account_number,
                'product_id': product.pk,
                'member_id': member.pk if member else None,
                'group_id': group.pk if group else None,
            },
            branch_id=branch_id,
        )

        if opening_balance > ZERO:
            self._validate_member_transaction(
                account,
                withdrawal=False,
                contribution_member_id=contribution_member_id,
            )
            self._post_transaction(
                account=account,
                transaction_type=SavingsTransaction.TYPE_DEPOSIT,
                amount=opening_balance,
                transaction_date=opened_at,
                payment_channel=SavingsTransaction.CHANNEL_CASH,
                idempotency_key=uuid.uuid5(key, 'opening-deposit'),
                contribution_member_id=contribution_member_id,
                narration='Opening deposit',
            )
        account._idempotent_replay = False
        return account

    @transaction.atomic
    def deposit(
        self,
        *,
        account_id,
        amount,
        transaction_date,
        payment_channel,
        idempotency_key,
        contribution_member_id=None,
        narration='',
    ):
        account = self._get_account_for_update(account_id)
        replay = self._existing_transaction(account, idempotency_key, {
            'transaction_type': SavingsTransaction.TYPE_DEPOSIT,
            'amount': amount,
            'transaction_date': transaction_date,
            'payment_channel': payment_channel,
            'contribution_member_id': contribution_member_id,
        })
        if replay:
            return replay
        self._validate_member_transaction(account, withdrawal=False, contribution_member_id=contribution_member_id)
        return self._post_transaction(
            account=account,
            transaction_type=SavingsTransaction.TYPE_DEPOSIT,
            amount=amount,
            transaction_date=transaction_date,
            payment_channel=payment_channel,
            idempotency_key=idempotency_key,
            contribution_member_id=contribution_member_id,
            narration=narration,
        )

    @transaction.atomic
    def credit_from_loan_repayment(
        self,
        *,
        account_id,
        member_id,
        amount,
        transaction_date,
        idempotency_key,
        journal_entry,
        narration,
    ):
        account = self._get_account_for_update(account_id)
        amount = self._validate_money(amount, allow_zero=False, field='amount')
        key = self._uuid_key(idempotency_key)
        existing = SavingsTransaction.objects.filter(
            account=account, idempotency_key=key
        ).first()
        if existing:
            if (
                existing.amount != amount
                or existing.transaction_date != transaction_date
                or existing.journal_entry_id != journal_entry.pk
            ):
                raise ValidationError({
                    'idempotency_key': 'This key was already used with different savings details.'
                })
            return existing
        if account.member_id != member_id or account.status != SavingsAccount.STATUS_ACTIVE:
            raise ValidationError({
                'savings_account': 'Select an active individual savings account for this borrower.'
            })
        if journal_entry.branch_id != account.branch_id:
            raise ValidationError('The savings transfer journal must belong to the account branch.')
        balance_before = account.balance
        balance_after = balance_before + amount
        if balance_after < account.product_term('minimum_balance'):
            raise ValidationError('The transfer would violate the savings minimum balance.')
        account.balance = balance_after
        account.version += 1
        self._save_account(account, update_fields=['balance', 'version', 'updated_at'])
        transaction_record = SavingsTransaction(
            branch_id=account.branch_id,
            account=account,
            transaction_type=SavingsTransaction.TYPE_DEPOSIT,
            status=SavingsTransaction.STATUS_POSTED,
            transaction_date=transaction_date,
            amount=amount,
            gross_amount=amount,
            tax_amount=ZERO,
            balance_before=balance_before,
            balance_after=balance_after,
            payment_channel=SavingsTransaction.CHANNEL_CASH,
            journal_entry=journal_entry,
            idempotency_key=key,
            narration=narration[:255],
            created_by=self.request.user,
        )
        transaction_record._posting_authorized = True
        try:
            transaction_record.full_clean()
            transaction_record.save()
        finally:
            del transaction_record._posting_authorized
        log_action(
            'LoanOverpaymentTransfer',
            'SavingsTransaction',
            transaction_record.pk,
            new_values={
                'loan_journal_id': journal_entry.pk,
                'amount': str(amount),
                'balance_after': str(balance_after),
            },
            branch_id=account.branch_id,
        )
        return transaction_record

    @transaction.atomic
    def withdraw(
        self,
        *,
        account_id,
        amount,
        transaction_date,
        payment_channel,
        idempotency_key,
        narration='',
    ):
        account = self._get_account_for_update(account_id)
        replay = self._existing_transaction(account, idempotency_key, {
            'transaction_type': SavingsTransaction.TYPE_WITHDRAWAL,
            'amount': amount,
            'transaction_date': transaction_date,
            'payment_channel': payment_channel,
        })
        if replay:
            return replay
        self._validate_member_transaction(account, withdrawal=True)
        self._validate_amount(amount)
        if not account.product_term('allow_withdrawals'):
            raise ValidationError({'amount': 'Withdrawals are disabled for this savings product.'})
        maximum_withdrawal = account.product_term('maximum_withdrawal')
        if maximum_withdrawal is not None and amount > maximum_withdrawal:
            raise ValidationError({
                'amount': f'The maximum withdrawal is {maximum_withdrawal}.'
            })
        if account.available_balance - amount < account.product_term('minimum_balance'):
            raise ValidationError({'amount': 'The withdrawal would breach the minimum available balance.'})

        threshold = account.product_term('withdrawal_approval_threshold')
        if threshold is not None and amount > threshold:
            account.reserved_balance += amount
            account.version += 1
            self._save_account(
                account,
                update_fields=['reserved_balance', 'version', 'updated_at'],
            )
            pending = SavingsTransaction(
                branch_id=account.branch_id,
                account=account,
                transaction_type=SavingsTransaction.TYPE_WITHDRAWAL,
                status=SavingsTransaction.STATUS_PENDING,
                transaction_date=transaction_date,
                amount=amount,
                gross_amount=amount,
                balance_before=account.balance,
                balance_after=account.balance,
                payment_channel=payment_channel,
                idempotency_key=self._uuid_key(idempotency_key),
                narration=narration.strip(),
                created_by=self.request.user,
            )
            pending.full_clean()
            pending.save()
            log_action(
                'WithdrawalRequested',
                'SavingsTransaction',
                pending.pk,
                new_values={'amount': str(amount), 'status': pending.status},
                branch_id=account.branch_id,
            )
            return pending
        return self._post_transaction(
            account=account,
            transaction_type=SavingsTransaction.TYPE_WITHDRAWAL,
            amount=amount,
            transaction_date=transaction_date,
            payment_channel=payment_channel,
            idempotency_key=idempotency_key,
            narration=narration,
        )

    @transaction.atomic
    def charge_fee(
        self,
        *,
        account_id,
        transaction_date,
        idempotency_key,
        narration='Product fee',
    ):
        account = self._get_account_for_update(account_id)
        replay = self._existing_transaction(account, idempotency_key, {
            'transaction_type': SavingsTransaction.TYPE_FEE,
            'amount': account.product_term('fee_amount'),
            'transaction_date': transaction_date,
        })
        if replay:
            return replay
        self._validate_member_transaction(account, withdrawal=True)
        amount = account.product_term('fee_amount')
        self._validate_amount(amount)
        if account.available_balance - amount < account.product_term('minimum_balance'):
            raise ValidationError({'amount': 'The fee would breach the minimum available balance.'})
        return self._post_transaction(
            account=account,
            transaction_type=SavingsTransaction.TYPE_FEE,
            amount=amount,
            transaction_date=transaction_date,
            payment_channel=SavingsTransaction.CHANNEL_CASH,
            idempotency_key=idempotency_key,
            narration=narration,
        )

    @transaction.atomic
    def approve_withdrawal(self, *, transaction_id):
        pending = SavingsTransaction.unscoped.select_for_update().filter(pk=transaction_id).first()
        if pending is None:
            raise SavingsTransaction.DoesNotExist
        self._ensure_branch_access(pending.branch_id)
        account = SavingsAccount.unscoped.select_for_update(of=('self',)).select_related(
            'product',
            'member',
            'group',
        ).get(pk=pending.account_id)
        if pending.status != SavingsTransaction.STATUS_PENDING:
            raise ValidationError('Only pending withdrawals may be approved.')
        self._validate_member_transaction(account, withdrawal=True)
        if pending.created_by_id == self.request.user.pk:
            raise ValidationError('The maker cannot approve their own withdrawal.')
        if account.reserved_balance < pending.amount:
            raise ValidationError('The reserved withdrawal amount is inconsistent with the account.')
        if account.balance - pending.amount < account.product_term('minimum_balance'):
            raise ValidationError('The withdrawal would breach the minimum balance.')

        balance_before = account.balance
        balance_after = balance_before - pending.amount
        self._validate_transaction_date(account, pending.transaction_date)
        entry = self._create_journal(
            account=account,
            transaction_type=SavingsTransaction.TYPE_WITHDRAWAL,
            amount=pending.amount,
            gross_amount=pending.amount,
            tax_amount=ZERO,
            transaction_date=pending.transaction_date,
            payment_channel=pending.payment_channel,
            idempotency_key=pending.idempotency_key,
            narration=pending.narration or 'Approved savings withdrawal',
        )
        account.balance = balance_after
        account.reserved_balance -= pending.amount
        account.version += 1
        self._save_account(
            account,
            update_fields=['balance', 'reserved_balance', 'version', 'updated_at'],
        )
        pending.balance_before = balance_before
        pending.balance_after = balance_after
        pending.journal_entry = entry
        pending.status = SavingsTransaction.STATUS_POSTED
        pending.approved_by = self.request.user
        pending._posting_authorized = True
        try:
            pending.full_clean()
            pending.save(update_fields=[
                'balance_before',
                'balance_after',
                'journal_entry',
                'status',
                'approved_by',
            ])
        finally:
            del pending._posting_authorized
        log_action(
            'ApproveWithdrawal',
            'SavingsTransaction',
            pending.pk,
            new_values={'amount': str(pending.amount), 'status': pending.status},
            branch_id=account.branch_id,
        )
        return pending

    @transaction.atomic
    def reject_withdrawal(self, *, transaction_id, reason):
        pending = SavingsTransaction.unscoped.select_for_update().filter(pk=transaction_id).first()
        if pending is None:
            raise SavingsTransaction.DoesNotExist
        self._ensure_branch_access(pending.branch_id)
        account = SavingsAccount.unscoped.select_for_update().get(pk=pending.account_id)
        if pending.status != SavingsTransaction.STATUS_PENDING:
            raise ValidationError('Only pending withdrawals may be rejected.')
        if pending.created_by_id == self.request.user.pk:
            raise ValidationError('The maker cannot reject their own withdrawal request.')
        if not reason.strip():
            raise ValidationError({'reason': 'A rejection reason is required.'})
        if account.reserved_balance < pending.amount:
            raise ValidationError('The reserved withdrawal amount is inconsistent with the account.')
        account.reserved_balance -= pending.amount
        account.version += 1
        self._save_account(
            account,
            update_fields=['reserved_balance', 'version', 'updated_at'],
        )
        pending.status = SavingsTransaction.STATUS_REJECTED
        pending.rejected_by = self.request.user
        pending.rejection_reason = reason.strip()
        pending._rejection_authorized = True
        try:
            pending.save(update_fields=['status', 'rejected_by', 'rejection_reason'])
        finally:
            del pending._rejection_authorized
        log_action(
            'RejectWithdrawal',
            'SavingsTransaction',
            pending.pk,
            new_values={'status': pending.status},
            remarks=reason.strip(),
            branch_id=account.branch_id,
        )
        return pending

    @transaction.atomic
    def reverse(self, *, transaction_id, reversal_date, reason):
        original = SavingsTransaction.unscoped.select_for_update().filter(pk=transaction_id).first()
        if original is None:
            raise SavingsTransaction.DoesNotExist
        self._ensure_branch_access(original.branch_id)
        if original.status != SavingsTransaction.STATUS_POSTED:
            raise ValidationError('Only posted savings transactions can be reversed.')
        if hasattr(original, 'reversal_transaction'):
            raise ValidationError('This savings transaction has already been reversed.')
        if not reason.strip():
            raise ValidationError({'reason': 'A reversal reason is required.'})
        account = SavingsAccount.unscoped.select_for_update().select_related('product').get(pk=original.account_id)
        if account.status not in {SavingsAccount.STATUS_ACTIVE, SavingsAccount.STATUS_DORMANT}:
            raise ValidationError('Only active or dormant accounts can have transactions reversed.')
        self._validate_transaction_date(account, reversal_date)
        balance_before = account.balance
        balance_delta = original.balance_after - original.balance_before
        balance_after = balance_before - balance_delta
        if balance_after < account.product_term('minimum_balance'):
            raise ValidationError('The reversal would breach the account minimum balance.')

        journal_reversal = JournalService(self.request).reverse(
            entry_id=original.journal_entry_id,
            reversal_date=reversal_date,
            reason=reason,
        )
        account.balance = balance_after
        account.version += 1
        self._save_account(account, update_fields=['balance', 'version', 'updated_at'])
        reversal = SavingsTransaction(
            branch_id=account.branch_id,
            account=account,
            transaction_type=SavingsTransaction.TYPE_REVERSAL,
            status=SavingsTransaction.STATUS_POSTED,
            transaction_date=reversal_date,
            amount=original.amount,
            gross_amount=original.gross_amount,
            tax_amount=original.tax_amount,
            balance_before=balance_before,
            balance_after=balance_after,
            payment_channel=original.payment_channel,
            journal_entry=journal_reversal,
            reversal_of=original,
            idempotency_key=uuid.uuid4(),
            narration=f'Reversal of transaction {original.pk}: {reason.strip()}'[:255],
            created_by=self.request.user,
        )
        reversal._posting_authorized = True
        try:
            reversal.full_clean()
            reversal.save()
        finally:
            del reversal._posting_authorized
        log_action(
            'Reverse',
            'SavingsTransaction',
            reversal.pk,
            old_values={'transaction_id': original.pk},
            new_values={'amount': str(reversal.amount), 'balance_after': str(balance_after)},
            remarks=reason.strip(),
            branch_id=account.branch_id,
        )
        return reversal

    @transaction.atomic
    def close_account(self, *, account_id):
        account = self._get_account_for_update(account_id)
        if account.status == SavingsAccount.STATUS_CLOSED:
            return account
        if account.status == SavingsAccount.STATUS_PENDING:
            raise ValidationError('A pending savings account cannot be closed.')
        if account.balance != ZERO or account.reserved_balance != ZERO:
            raise ValidationError('An account can be closed only after all funds and reservations are cleared.')
        account.status = SavingsAccount.STATUS_CLOSED
        account.closed_at = timezone.localdate()
        account.version += 1
        self._save_account(
            account,
            update_fields=['status', 'closed_at', 'version', 'updated_at'],
        )
        log_action(
            'Close',
            'SavingsAccount',
            account.pk,
            new_values={'status': account.status},
            branch_id=account.branch_id,
        )
        return account

    @transaction.atomic
    def mark_dormant_accounts(self, *, as_of_date):
        user = self._active_user()
        branch_ids = user.accessible_branch_ids(
            getattr(self.request, 'active_branch_id', None)
        )
        accounts = SavingsAccount.unscoped.select_for_update(of=('self',)).filter(
            branch_id__in=branch_ids,
            status=SavingsAccount.STATUS_ACTIVE,
            product__dormant_after_days__isnull=False,
            reserved_balance=ZERO,
        ).select_related('product')
        changed = []
        for account in accounts.iterator():
            if SavingsTransaction.unscoped.filter(
                account=account,
                status=SavingsTransaction.STATUS_PENDING,
            ).exists():
                continue
            last_activity = SavingsTransaction.unscoped.filter(
                account=account,
                status=SavingsTransaction.STATUS_POSTED,
                transaction_type__in=[
                    SavingsTransaction.TYPE_DEPOSIT,
                    SavingsTransaction.TYPE_WITHDRAWAL,
                ],
            ).order_by('-transaction_date', '-pk').values_list(
                'transaction_date',
                flat=True,
            ).first() or account.opened_at
            dormant_after = last_activity + timedelta(
                days=account.product_term('dormant_after_days')
            )
            if as_of_date < dormant_after:
                continue
            account.status = SavingsAccount.STATUS_DORMANT
            account.version += 1
            self._save_account(
                account,
                update_fields=['status', 'version', 'updated_at'],
            )
            log_action(
                'MarkDormant',
                'SavingsAccount',
                account.pk,
                old_values={'status': SavingsAccount.STATUS_ACTIVE},
                new_values={
                    'status': SavingsAccount.STATUS_DORMANT,
                    'last_activity': last_activity.isoformat(),
                    'as_of_date': as_of_date.isoformat(),
                },
                branch_id=account.branch_id,
            )
            changed.append(account)
        return changed

    @transaction.atomic
    def reactivate_account(self, *, account_id, reason):
        account = self._get_account_for_update(account_id)
        if account.status != SavingsAccount.STATUS_DORMANT:
            raise ValidationError('Only dormant savings accounts can be reactivated.')
        if not reason.strip():
            raise ValidationError({'reason': 'A reactivation reason is required.'})
        account.status = SavingsAccount.STATUS_ACTIVE
        account.version += 1
        self._save_account(
            account,
            update_fields=['status', 'version', 'updated_at'],
        )
        log_action(
            'Reactivate',
            'SavingsAccount',
            account.pk,
            old_values={'status': SavingsAccount.STATUS_DORMANT},
            new_values={'status': SavingsAccount.STATUS_ACTIVE},
            remarks=reason.strip(),
            branch_id=account.branch_id,
        )
        return account

    def reconcile_savings(self, *, as_of_date, branch_id=None):
        user = self._active_user()
        accessible_branch_ids = user.accessible_branch_ids(
            getattr(self.request, 'active_branch_id', None)
        )
        if branch_id is not None:
            self._ensure_branch_access(branch_id)
            accessible_branch_ids = [branch_id]

        mapping = self._mapping('member_savings')
        latest_balance = SavingsTransaction.unscoped.filter(
            account_id=OuterRef('pk'),
            status=SavingsTransaction.STATUS_POSTED,
            transaction_date__lte=as_of_date,
        ).order_by('-transaction_date', '-pk').values('balance_after')[:1]
        subledger_total = SavingsAccount.unscoped.filter(
            branch_id__in=accessible_branch_ids,
            opened_at__lte=as_of_date,
        ).annotate(
            as_of_balance=Subquery(latest_balance),
        ).aggregate(total=Sum('as_of_balance'))['total'] or ZERO
        ledger_totals = JournalEntry.unscoped.filter(
            branch_id__in=accessible_branch_ids,
            status=JournalEntry.STATUS_POSTED,
            journal_date__lte=as_of_date,
            lines__account_id=mapping.account_id,
        ).aggregate(
            credits=Sum('lines__credit'),
            debits=Sum('lines__debit'),
        )
        ledger_total = (ledger_totals['credits'] or ZERO) - (ledger_totals['debits'] or ZERO)
        variance = subledger_total - ledger_total
        return {
            'as_of_date': as_of_date,
            'branch_ids': accessible_branch_ids,
            'subledger_balance': subledger_total,
            'ledger_balance': ledger_total,
            'variance': variance,
            'is_reconciled': variance == ZERO,
            'ledger_account': mapping.account,
        }

    @transaction.atomic
    def post_interest(self, *, account_id, start_date, end_date, idempotency_key):
        account = self._get_account_for_update(account_id)
        replay = self._existing_transaction(account, idempotency_key, {
            'transaction_type': SavingsTransaction.TYPE_INTEREST,
            'transaction_date': end_date,
            'period_start': start_date,
            'period_end': end_date,
        })
        if replay:
            return replay
        if end_date < start_date:
            raise ValidationError('The interest period end date must not precede its start date.')
        if account.status not in {SavingsAccount.STATUS_ACTIVE, SavingsAccount.STATUS_DORMANT}:
            raise ValidationError('Only active or eligible dormant accounts earn interest.')
        if (
            account.status == SavingsAccount.STATUS_DORMANT
            and not account.product_term('pays_interest_when_dormant')
        ):
            raise ValidationError('This savings product does not pay interest on dormant accounts.')
        self._validate_transaction_date(account, end_date)
        self._validate_interest_period(
            account.product_term('posting_frequency'),
            start_date,
            end_date,
        )
        if SavingsTransaction.unscoped.filter(
            account=account,
            transaction_type=SavingsTransaction.TYPE_INTEREST,
            status=SavingsTransaction.STATUS_POSTED,
            period_start=start_date,
            period_end=end_date,
        ).exists():
            raise ValidationError('Interest has already been posted for this period.')
        gross_interest = self.calculate_interest(
            account_id=account.pk,
            start_date=start_date,
            end_date=end_date,
        )
        if gross_interest <= ZERO:
            raise ValidationError('There is no positive interest to post for this period.')
        tax_amount = (
            gross_interest * account.product_term('withholding_tax_rate')
        ).quantize(
            CENT,
            rounding=ROUND_HALF_UP,
        )
        net_amount = gross_interest - tax_amount
        if net_amount <= ZERO:
            raise ValidationError('Interest after withholding must be greater than zero.')
        return self._post_transaction(
            account=account,
            transaction_type=SavingsTransaction.TYPE_INTEREST,
            amount=net_amount,
            gross_amount=gross_interest,
            tax_amount=tax_amount,
            transaction_date=end_date,
            payment_channel=SavingsTransaction.CHANNEL_CASH,
            idempotency_key=idempotency_key,
            narration=f'Interest from {start_date} through {end_date}',
            period_start=start_date,
            period_end=end_date,
        )

    def calculate_interest(self, *, account_id, start_date, end_date):
        if end_date < start_date:
            raise ValidationError('The interest period end date must not precede its start date.')
        account = SavingsAccount.unscoped.select_related('product').get(pk=account_id)
        self._ensure_branch_access(account.branch_id)
        if account.status not in {SavingsAccount.STATUS_ACTIVE, SavingsAccount.STATUS_DORMANT}:
            return ZERO
        if (
            account.status == SavingsAccount.STATUS_DORMANT
            and not account.product_term('pays_interest_when_dormant')
        ):
            return ZERO
        annual_interest_rate = account.product_term('annual_interest_rate')
        interest_method = account.product_term('interest_method')
        prior = SavingsTransaction.unscoped.filter(
            account=account,
            status=SavingsTransaction.STATUS_POSTED,
            transaction_date__lt=start_date,
        ).order_by('-transaction_date', '-pk').values_list('balance_after', flat=True).first()
        balance = prior if prior is not None else ZERO
        transaction_rows = SavingsTransaction.unscoped.filter(
            account=account,
            status=SavingsTransaction.STATUS_POSTED,
            transaction_date__range=(start_date, end_date),
        ).order_by('transaction_date', 'pk').values_list('transaction_date', 'balance_after')
        day_balances = {}
        for transaction_date, balance_after in transaction_rows:
            day_balances[transaction_date] = balance_after

        daily_interest_sum = ZERO
        minimum_balance = None
        day_count = (end_date - start_date).days + 1
        for offset in range(day_count):
            current_date = start_date + timedelta(days=offset)
            if current_date in day_balances:
                balance = day_balances[current_date]
            minimum_balance = balance if minimum_balance is None else min(minimum_balance, balance)
            daily_interest_sum += balance * annual_interest_rate / YEAR_DAYS

        if interest_method == SavingsProduct.METHOD_MINIMUM_BALANCE:
            interest = (
                (minimum_balance or ZERO)
                * annual_interest_rate
                * Decimal(day_count)
                / YEAR_DAYS
            )
        else:
            interest = daily_interest_sum
        return interest.quantize(CENT, rounding=ROUND_HALF_UP)


    def _post_transaction(
        self,
        *,
        account,
        transaction_type,
        amount,
        transaction_date,
        payment_channel,
        idempotency_key,
        narration='',
        contribution_member_id=None,
        gross_amount=None,
        tax_amount=ZERO,
        period_start=None,
        period_end=None,
    ):
        self._ensure_account_active(
            account,
            allow_dormant_interest=transaction_type == SavingsTransaction.TYPE_INTEREST,
        )
        self._validate_amount(amount)
        self._validate_transaction_date(account, transaction_date)
        if transaction_type in {
            SavingsTransaction.TYPE_WITHDRAWAL,
            SavingsTransaction.TYPE_FEE,
        }:
            if account.available_balance - amount < account.product_term('minimum_balance'):
                raise ValidationError({
                    'amount': 'The transaction would breach the minimum available balance.'
                })
            balance_delta = -amount
        else:
            balance_delta = amount
        balance_before = account.balance
        balance_after = balance_before + balance_delta
        self._validate_money(balance_after, allow_zero=True, field='balance')
        if balance_after < account.product_term('minimum_balance'):
            raise ValidationError({'amount': 'The transaction would breach the minimum balance.'})
        gross_amount = amount if gross_amount is None else gross_amount
        self._validate_money(gross_amount, allow_zero=False, field='gross_amount')
        self._validate_money(tax_amount, allow_zero=True, field='tax_amount')
        if (
            transaction_type == SavingsTransaction.TYPE_INTEREST
            and gross_amount != amount + tax_amount
        ):
            raise ValidationError('Gross interest must equal posted interest plus withholding tax.')
        entry = self._create_journal(
            account=account,
            transaction_type=transaction_type,
            amount=amount,
            gross_amount=gross_amount,
            tax_amount=tax_amount,
            transaction_date=transaction_date,
            payment_channel=payment_channel,
            idempotency_key=self._uuid_key(idempotency_key),
            narration=narration,
        )
        account.balance = balance_after
        account.version += 1
        self._save_account(account, update_fields=['balance', 'version', 'updated_at'])
        savings_transaction = SavingsTransaction(
            branch_id=account.branch_id,
            account=account,
            transaction_type=transaction_type,
            status=SavingsTransaction.STATUS_POSTED,
            transaction_date=transaction_date,
            amount=amount,
            gross_amount=gross_amount,
            tax_amount=tax_amount,
            balance_before=balance_before,
            balance_after=balance_after,
            payment_channel=payment_channel,
            contribution_member_id=contribution_member_id,
            journal_entry=entry,
            idempotency_key=self._uuid_key(idempotency_key),
            period_start=period_start,
            period_end=period_end,
            narration=narration.strip(),
            created_by=self.request.user,
        )
        savings_transaction._posting_authorized = True
        try:
            savings_transaction.full_clean()
            savings_transaction.save()
        finally:
            del savings_transaction._posting_authorized
        log_action(
            'Post',
            'SavingsTransaction',
            savings_transaction.pk,
            new_values={
                'type': transaction_type,
                'amount': str(amount),
                'balance_after': str(balance_after),
            },
            branch_id=account.branch_id,
        )
        return savings_transaction

    def _create_journal(
        self,
        *,
        account,
        transaction_type,
        amount,
        gross_amount,
        tax_amount,
        transaction_date,
        payment_channel,
        idempotency_key,
        narration,
    ):
        journal_service = JournalService(self.request)
        entry = journal_service.create_entry(
            branch_id=account.branch_id,
            journal_date=transaction_date,
            narration=narration or f'Savings {transaction_type} for {account.account_number}',
            voucher_type=VoucherSequence.VOUCHER_SYSTEM,
            source_type='savings',
            source_id=account.account_number,
            idempotency_key=uuid.uuid5(idempotency_key, 'journal'),
        )
        if transaction_type == SavingsTransaction.TYPE_DEPOSIT:
            cash_mapping = self._mapping(
                'cash_in_hand' if payment_channel == SavingsTransaction.CHANNEL_CASH else 'bank_accounts'
            )
            savings_mapping = self._mapping('member_savings')
            self._add_journal_line(journal_service, entry, cash_mapping.account_id, debit=amount)
            self._add_journal_line(journal_service, entry, savings_mapping.account_id, credit=amount)
        elif transaction_type == SavingsTransaction.TYPE_WITHDRAWAL:
            cash_mapping = self._mapping(
                'cash_in_hand' if payment_channel == SavingsTransaction.CHANNEL_CASH else 'bank_accounts'
            )
            savings_mapping = self._mapping('member_savings')
            self._add_journal_line(journal_service, entry, savings_mapping.account_id, debit=amount)
            self._add_journal_line(journal_service, entry, cash_mapping.account_id, credit=amount)
        elif transaction_type == SavingsTransaction.TYPE_INTEREST:
            expense_mapping = self._mapping('interest_expense')
            savings_mapping = self._mapping('member_savings')
            self._add_journal_line(journal_service, entry, expense_mapping.account_id, debit=gross_amount)
            self._add_journal_line(journal_service, entry, savings_mapping.account_id, credit=amount)
            if tax_amount > ZERO:
                tax_mapping = self._mapping('withholding_tax_payable')
                self._add_journal_line(journal_service, entry, tax_mapping.account_id, credit=tax_amount)
        elif transaction_type == SavingsTransaction.TYPE_FEE:
            savings_mapping = self._mapping('member_savings')
            fee_mapping = self._mapping('fee_income')
            self._add_journal_line(journal_service, entry, savings_mapping.account_id, debit=amount)
            self._add_journal_line(journal_service, entry, fee_mapping.account_id, credit=amount)
        else:
            raise ValidationError({'transaction_type': 'This savings transaction type cannot be posted directly.'})
        return journal_service.post(entry_id=entry.pk)

    @staticmethod
    def _add_journal_line(service, entry, account_id, *, debit=ZERO, credit=ZERO):
        service.add_line(
            entry_id=entry.pk,
            account_id=account_id,
            debit=debit,
            credit=credit,
        )

    @staticmethod
    def _mapping(key):
        mapping = SystemAccountMapping.objects.select_related('account').filter(
            key=key,
            account__is_active=True,
            account__allows_direct_posting=True,
        ).first()
        if mapping is None:
            raise ValidationError(
                f'The system account "{key}" must be mapped to an active postable account first.'
            )
        if mapping.account.account_type != SystemAccountMapping.EXPECTED_ACCOUNT_TYPES[key]:
            raise ValidationError(
                f'The system account "{key}" is mapped to an account with the wrong type.'
            )
        return mapping

    def _get_account_for_update(self, account_id):
        account = SavingsAccount.unscoped.select_for_update(of=('self',)).select_related(
            'product', 'member', 'group'
        ).filter(pk=account_id).first()
        if account is None:
            raise SavingsAccount.DoesNotExist
        self._ensure_branch_access(account.branch_id)
        return account

    def _existing_transaction(self, account, idempotency_key, expected=None):
        key = self._uuid_key(idempotency_key)
        existing = SavingsTransaction.unscoped.filter(
            created_by=self.request.user,
            idempotency_key=key,
        ).first()
        if existing:
            if existing.account_id != account.pk:
                raise ValidationError({'idempotency_key': 'This key was already used for another account.'})
            for field, expected_value in (expected or {}).items():
                if getattr(existing, f'{field}_id', None) == expected_value:
                    continue
                actual_value = getattr(existing, field)
                if actual_value != expected_value:
                    raise ValidationError({
                        'idempotency_key': 'This key was already used with different transaction details.'
                    })
            existing._idempotent_replay = True
            return existing
        return None

    def _validate_member_transaction(self, account, *, withdrawal, contribution_member_id=None):
        self._ensure_account_active(account)
        if account.member_id:
            if account.member.status not in {Member.STATUS_ACTIVE, Member.STATUS_INACTIVE}:
                raise ValidationError('Savings transactions are blocked for pending or suspended members.')
            if withdrawal and account.member.status != Member.STATUS_ACTIVE:
                raise ValidationError('Only active members may withdraw savings.')
        elif account.group_id:
            if contribution_member_id is not None:
                member = Member.unscoped.filter(
                    pk=contribution_member_id,
                    group_id=account.group_id,
                    branch_id=account.branch_id,
                ).first()
                if member is None or member.status == Member.STATUS_SUSPENDED:
                    raise ValidationError({
                        'contribution_member': 'Select a non-suspended member in this group.'
                    })
            elif not withdrawal:
                raise ValidationError({'contribution_member': 'Select the contributing group member.'})

    def _ensure_account_active(self, account, *, allow_dormant_interest=False):
        allowed_statuses = {SavingsAccount.STATUS_ACTIVE}
        if allow_dormant_interest and account.product_term('pays_interest_when_dormant'):
            allowed_statuses.add(SavingsAccount.STATUS_DORMANT)
        if account.status not in allowed_statuses:
            raise ValidationError('Savings transactions require an active account.')

    @staticmethod
    def _save_account(account, update_fields=None):
        account._savings_update_authorized = True
        try:
            if update_fields is None:
                account.save()
            else:
                account.save(update_fields=update_fields)
        finally:
            del account._savings_update_authorized

    @staticmethod
    def _validate_transaction_date(account, transaction_date):
        latest_date = SavingsTransaction.unscoped.filter(
            account=account,
            status=SavingsTransaction.STATUS_POSTED,
        ).order_by('-transaction_date', '-pk').values_list(
            'transaction_date',
            flat=True,
        ).first()
        if latest_date and transaction_date < latest_date:
            raise ValidationError({
                'transaction_date': 'A savings posting cannot be backdated before the latest posted transaction.'
            })

    def _ensure_branch_access(self, branch_id):
        user = self._active_user()
        if branch_id not in user.accessible_branch_ids(
            getattr(self.request, 'active_branch_id', None)
        ):
            raise ValidationError({'branch': 'You cannot access this branch.'})

    def _active_user(self):
        user = getattr(self.request, 'user', None)
        if user is None or not user.is_authenticated or not user.is_active:
            raise ValidationError('An active user is required for savings transactions.')
        return user

    @staticmethod
    def _validate_amount(amount):
        SavingsService._validate_money(amount, allow_zero=False, field='amount')

    @staticmethod
    def _validate_money(amount, *, allow_zero, field):
        if not isinstance(amount, Decimal) or not amount.is_finite():
            raise ValidationError({
                field: 'Amount must be a finite Decimal value.'
            })
        if (
            amount < ZERO
            or (not allow_zero and amount == ZERO)
            or amount > MAX_MONEY
            or amount != amount.quantize(CENT)
        ):
            minimum = 'non-negative' if allow_zero else 'positive'
            raise ValidationError({
                field: f'Amount must be a {minimum} Decimal with no more than two fractional digits.'
            })

    @staticmethod
    def _uuid_key(key):
        if key is None:
            return uuid.uuid4()
        try:
            return uuid.UUID(str(key))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValidationError({'idempotency_key': 'A valid idempotency key is required.'}) from exc

    @staticmethod
    def _validate_interest_period(frequency, start_date, end_date):
        last_day = monthrange(end_date.year, end_date.month)[1]
        if end_date.day != last_day:
            raise ValidationError('Interest must be posted on the final day of its posting period.')
        if (
            frequency == SavingsProduct.FREQUENCY_MONTHLY
            and (
                (start_date.year, start_date.month)
                != (end_date.year, end_date.month)
                or start_date.day != 1
            )
        ):
            raise ValidationError('Monthly interest must cover one complete calendar month.')
        if frequency == SavingsProduct.FREQUENCY_QUARTERLY and end_date.month not in {3, 6, 9, 12}:
            raise ValidationError('Quarterly interest must be posted at the end of a calendar quarter.')
        if frequency == SavingsProduct.FREQUENCY_QUARTERLY:
            quarter_start_month = ((end_date.month - 1) // 3) * 3 + 1
            if (start_date.year, start_date.month, start_date.day) != (
                end_date.year,
                quarter_start_month,
                1,
            ):
                raise ValidationError('Quarterly interest must cover one complete calendar quarter.')
        if frequency == SavingsProduct.FREQUENCY_HALF_YEARLY and end_date.month not in {6, 12}:
            raise ValidationError('Half-yearly interest must be posted at June or December month-end.')
        if frequency == SavingsProduct.FREQUENCY_HALF_YEARLY:
            expected_start = (end_date.year, 1, 1) if end_date.month == 6 else (end_date.year, 7, 1)
            if (start_date.year, start_date.month, start_date.day) != expected_start:
                raise ValidationError('Half-yearly interest must cover one complete half-year.')
        if frequency == SavingsProduct.FREQUENCY_YEARLY and (end_date.month, end_date.day) != (12, 31):
            raise ValidationError('Yearly interest must be posted on December 31.')
        if frequency == SavingsProduct.FREQUENCY_YEARLY and (
            start_date.year,
            start_date.month,
            start_date.day,
        ) != (end_date.year, 1, 1):
            raise ValidationError('Yearly interest must cover the complete calendar year.')
