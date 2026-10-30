import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from core.audit.services import log_action
from core.branch.models import Branch, BranchClosedDay

from .models import (
    Account,
    AccountingPeriod,
    AccountReconciliation,
    FiscalYear,
    JournalEntry,
    JournalLine,
    VoucherSequence,
)

ZERO = Decimal('0.00')


class JournalService:
    def __init__(self, request):
        self.request = request

    @transaction.atomic
    def create_entry(
        self,
        *,
        branch_id,
        journal_date,
        narration,
        voucher_type=VoucherSequence.VOUCHER_JOURNAL,
        requires_approval=False,
        source_type='',
        source_id='',
        idempotency_key=None,
    ):
        user = self.request.user
        if not user.is_authenticated or not user.is_active:
            raise ValidationError('An active user is required to create a journal entry.')
        if branch_id not in user.accessible_branch_ids(
            getattr(self.request, 'active_branch_id', None)
        ):
            raise ValidationError({'branch': 'You cannot post in this branch.'})
        if idempotency_key is None:
            idempotency_key = uuid.uuid4()
        try:
            idempotency_key = uuid.UUID(str(idempotency_key))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValidationError({'idempotency_key': 'A valid idempotency key is required.'}) from exc
        existing_entry = JournalEntry.unscoped.filter(
            created_by=user,
            idempotency_key=idempotency_key,
        ).first()
        if existing_entry:
            if existing_entry.branch_id != branch_id:
                raise ValidationError({'idempotency_key': 'This key was already used for another branch.'})
            existing_entry._idempotent_replay = True
            return existing_entry

        branch = Branch.unscoped.select_for_update().filter(pk=branch_id, is_active=True).first()
        if branch is None:
            raise ValidationError({'branch': 'The selected branch is not active.'})
        self._ensure_business_date_open(branch_id, journal_date)
        fiscal_year = FiscalYear.objects.select_for_update().filter(
            start_date__lte=journal_date,
            end_date__gte=journal_date,
        ).first()
        if fiscal_year is None or fiscal_year.is_closed:
            raise ValidationError({'journal_date': 'No open fiscal year contains this date.'})
        period = AccountingPeriod.objects.select_for_update().filter(
            fiscal_year=fiscal_year,
            start_date__lte=journal_date,
            end_date__gte=journal_date,
        ).first()
        if period is None or period.is_closed:
            raise ValidationError({'journal_date': 'No open accounting period contains this date.'})

        sequence, _ = VoucherSequence.unscoped.get_or_create(
            branch=branch,
            fiscal_year=fiscal_year,
            voucher_type=voucher_type,
            defaults={'next_number': 1},
        )
        sequence = VoucherSequence.unscoped.select_for_update().get(pk=sequence.pk)
        voucher_number = (
            f'{branch.code}-{fiscal_year.start_date.year}-'
            f'{voucher_type.upper()}-{sequence.next_number:06d}'
        )
        sequence.next_number += 1
        sequence.save(update_fields=['next_number'])

        entry = JournalEntry(
            branch=branch,
            fiscal_year=fiscal_year,
            period=period,
            voucher_type=voucher_type,
            voucher_number=voucher_number,
            journal_date=journal_date,
            narration=narration.strip(),
            idempotency_key=idempotency_key,
            source_type=source_type,
            source_id=str(source_id),
            requires_approval=requires_approval,
            created_by=user,
        )
        entry.full_clean()
        entry.save()
        entry._idempotent_replay = False
        log_action(
            'Create',
            'JournalEntry',
            entry.pk,
            new_values={'voucher_number': voucher_number, 'status': entry.status},
            branch_id=branch.pk,
        )
        return entry

    @transaction.atomic
    def add_line(self, *, entry_id, account_id, debit=ZERO, credit=ZERO, narration=''):
        entry = JournalEntry.unscoped.select_for_update().filter(pk=entry_id).first()
        if entry is None:
            raise JournalEntry.DoesNotExist
        self._ensure_branch_access(entry.branch_id)
        if entry.status != JournalEntry.STATUS_DRAFT:
            raise ValidationError('Journal lines can only be changed on draft entries.')
        if not isinstance(debit, Decimal) or not isinstance(credit, Decimal):
            raise ValidationError('Journal amounts must use Decimal values.')

        account = Account.objects.select_for_update().filter(
            pk=account_id,
            is_active=True,
            allows_direct_posting=True,
        ).first()
        if account is None:
            raise ValidationError({'account': 'Select an active, postable account.'})
        line = JournalLine(
            entry=entry,
            account=account,
            debit=debit,
            credit=credit,
            narration=narration.strip(),
        )
        line.full_clean()
        line.save()
        return line

    @transaction.atomic
    def submit_for_approval(self, *, entry_id):
        entry = JournalEntry.unscoped.select_for_update().filter(pk=entry_id).first()
        if entry is None:
            raise JournalEntry.DoesNotExist
        self._ensure_branch_access(entry.branch_id)
        if entry.status != JournalEntry.STATUS_DRAFT or not entry.requires_approval:
            raise ValidationError('This journal entry is not awaiting approval.')
        self._validate_balanced_entry(entry)
        entry.status = JournalEntry.STATUS_PENDING
        entry.save(update_fields=['status'])
        log_action(
            'SubmitForApproval',
            'JournalEntry',
            entry.pk,
            new_values={'status': entry.status},
            branch_id=entry.branch_id,
        )
        return entry

    @transaction.atomic
    def post(self, *, entry_id):
        entry = JournalEntry.unscoped.select_for_update().filter(pk=entry_id).first()
        if entry is None:
            raise JournalEntry.DoesNotExist
        self._ensure_branch_access(entry.branch_id)
        if entry.status not in {JournalEntry.STATUS_DRAFT, JournalEntry.STATUS_PENDING}:
            raise ValidationError('Only draft journal entries may be posted.')
        if entry.requires_approval:
            if entry.status != JournalEntry.STATUS_PENDING:
                raise ValidationError('Submit this journal entry for approval before posting.')
            if entry.created_by_id == self.request.user.pk:
                raise ValidationError('The maker cannot approve their own journal entry.')

        branch = Branch.unscoped.select_for_update().filter(
            pk=entry.branch_id, is_active=True
        ).first()
        if branch is None:
            raise ValidationError({'branch': 'The journal branch is not active.'})
        self._ensure_business_date_open(entry.branch_id, entry.journal_date)
        period = AccountingPeriod.objects.select_for_update().get(pk=entry.period_id)
        fiscal_year = FiscalYear.objects.select_for_update().get(pk=entry.fiscal_year_id)
        if period.is_closed or fiscal_year.is_closed:
            raise ValidationError('Entries cannot be posted into a closed accounting period.')
        if not Branch.unscoped.select_for_update().filter(
            pk=entry.branch_id,
            is_active=True,
        ).exists():
            raise ValidationError({'branch': 'The journal branch is not active.'})
        self._validate_balanced_entry(entry)
        line_account_ids = entry.lines.values_list('account_id', flat=True)
        if AccountReconciliation.objects.filter(
            branch_id=entry.branch_id,
            account_id__in=line_account_ids,
            status=AccountReconciliation.STATUS_RECONCILED,
            as_of_date__gte=entry.journal_date,
        ).exists():
            raise ValidationError('A reconciled account cannot receive a backdated posting.')
        entry.status = JournalEntry.STATUS_POSTED
        entry.posted_by = self.request.user
        entry.posted_at = timezone.now()
        entry._posting_authorized = True
        try:
            entry.save(update_fields=['status', 'posted_by', 'posted_at'])
        finally:
            del entry._posting_authorized
        log_action(
            'Post',
            'JournalEntry',
            entry.pk,
            new_values={'status': entry.status, 'voucher_number': entry.voucher_number},
            branch_id=entry.branch_id,
        )
        return entry

    @transaction.atomic
    def cancel(self, *, entry_id, reason):
        entry = JournalEntry.unscoped.select_for_update().filter(pk=entry_id).first()
        if entry is None:
            raise JournalEntry.DoesNotExist
        self._ensure_branch_access(entry.branch_id)
        if entry.status not in {JournalEntry.STATUS_DRAFT, JournalEntry.STATUS_PENDING}:
            raise ValidationError('Only draft or pending entries may be cancelled.')
        if not reason.strip():
            raise ValidationError({'reason': 'A cancellation reason is required.'})
        old_status = entry.status
        entry.status = JournalEntry.STATUS_CANCELLED
        entry.save(update_fields=['status'])
        log_action(
            'Cancel',
            'JournalEntry',
            entry.pk,
            old_values={'status': old_status},
            new_values={'status': entry.status},
            remarks=reason.strip(),
            branch_id=entry.branch_id,
        )
        return entry

    @transaction.atomic
    def reverse(self, *, entry_id, reversal_date, reason):
        original = JournalEntry.unscoped.select_for_update().filter(pk=entry_id).first()
        if original is None:
            raise JournalEntry.DoesNotExist
        self._ensure_branch_access(original.branch_id)
        if original.status != JournalEntry.STATUS_POSTED:
            raise ValidationError('Only posted journal entries can be reversed.')
        if hasattr(original, 'reversal_entry'):
            raise ValidationError('This journal entry has already been reversed.')
        if not reason.strip():
            raise ValidationError({'reason': 'A reversal reason is required.'})

        reversal = self.create_entry(
            branch_id=original.branch_id,
            journal_date=reversal_date,
            narration=f'Reversal of {original.voucher_number}: {reason.strip()}',
            voucher_type=original.voucher_type,
            source_type='journal_reversal',
            source_id=original.pk,
        )
        reversal.reversal_of = original
        reversal.save(update_fields=['reversal_of'])
        for line in original.lines.select_related('account').order_by('pk'):
            self.add_line(
                entry_id=reversal.pk,
                account_id=line.account_id,
                debit=line.credit,
                credit=line.debit,
                narration=f'Reversal: {line.narration}'[:255],
            )
        return self.post(entry_id=reversal.pk)

    def _ensure_branch_access(self, branch_id):
        user = self.request.user
        if (
            not user.is_authenticated
            or not user.is_active
            or branch_id not in user.accessible_branch_ids(
                getattr(self.request, 'active_branch_id', None)
            )
        ):
            raise ValidationError({'branch': 'You cannot access this branch.'})

    @staticmethod
    def _ensure_business_date_open(branch_id, journal_date):
        if BranchClosedDay.objects.filter(
            branch_id=branch_id,
            business_date=journal_date,
            is_closed=True,
        ).exists():
            raise ValidationError(
                f'Business date {journal_date} is closed for branch {branch_id}; reopen it before posting.'
            )

    @staticmethod
    def _validate_balanced_entry(entry):
        lines = list(entry.lines.select_for_update().select_related('account'))
        if len(lines) < 2:
            raise ValidationError('A journal entry must contain at least two lines.')
        if any(not line.account.is_active or not line.account.allows_direct_posting for line in lines):
            raise ValidationError('Every journal line must use an active, postable account.')
        if any(line.debit < 0 or line.credit < 0 for line in lines):
            raise ValidationError('Journal amounts cannot be negative.')
        debits = sum((line.debit for line in lines), ZERO)
        credits = sum((line.credit for line in lines), ZERO)
        if debits <= ZERO or debits != credits:
            raise ValidationError('Total debits must equal total credits and be greater than zero.')


def build_trial_balance(*, start_date, end_date, branch_ids):
    if start_date > end_date:
        raise ValidationError('The start date must be on or before the end date.')
    scoped_branch_ids = set(branch_ids)
    if not scoped_branch_ids:
        return {
            'accounts': [],
            'totals': {
                'opening_debit': ZERO,
                'opening_credit': ZERO,
                'debit': ZERO,
                'credit': ZERO,
                'closing_debit': ZERO,
                'closing_credit': ZERO,
            },
        }

    posted_lines = JournalLine.objects.filter(
        entry__branch_id__in=scoped_branch_ids,
        entry__status=JournalEntry.STATUS_POSTED,
    )
    opening_totals = {
        row['account_id']: (row['debit'] or ZERO) - (row['credit'] or ZERO)
        for row in posted_lines.filter(entry__journal_date__lt=start_date)
        .values('account_id')
        .annotate(debit=Sum('debit'), credit=Sum('credit'))
    }
    activity_totals = {
        row['account_id']: (row['debit'] or ZERO, row['credit'] or ZERO)
        for row in posted_lines.filter(
            entry__journal_date__range=(start_date, end_date)
        )
        .values('account_id')
        .annotate(debit=Sum('debit'), credit=Sum('credit'))
    }

    accounts = []
    totals = {
        'opening_debit': ZERO,
        'opening_credit': ZERO,
        'debit': ZERO,
        'credit': ZERO,
        'closing_debit': ZERO,
        'closing_credit': ZERO,
    }
    used_account_ids = set(opening_totals) | set(activity_totals)
    for account in Account.objects.filter(pk__in=used_account_ids).order_by('code'):
        opening_net = opening_totals.get(account.pk, ZERO)
        debit, credit = activity_totals.get(account.pk, (ZERO, ZERO))
        closing_net = opening_net + debit - credit
        row = {
            'account': account,
            'opening_debit': max(opening_net, ZERO),
            'opening_credit': max(-opening_net, ZERO),
            'debit': debit,
            'credit': credit,
            'closing_debit': max(closing_net, ZERO),
            'closing_credit': max(-closing_net, ZERO),
        }
        accounts.append(row)
        for key in totals:
            totals[key] += row[key]
    return {'accounts': accounts, 'totals': totals}


class ReconciliationService:
    def __init__(self, request):
        self.request = request

    @transaction.atomic
    def create(self, *, branch_id, account_id, as_of_date, statement_balance, notes=''):
        self._ensure_branch_access(branch_id)
        if not Branch.unscoped.select_for_update().filter(pk=branch_id, is_active=True).exists():
            raise ValidationError({'branch': 'The selected branch is not active.'})
        if not isinstance(statement_balance, Decimal) or statement_balance < ZERO:
            raise ValidationError({'statement_balance': 'Enter a non-negative Decimal balance.'})
        if AccountReconciliation.objects.filter(
            branch_id=branch_id,
            account_id=account_id,
            as_of_date=as_of_date,
        ).exists():
            raise ValidationError('A reconciliation already exists for this account and date.')
        account = Account.objects.select_for_update().filter(
            pk=account_id,
            account_type=Account.ASSET,
            is_active=True,
        ).first()
        if account is None:
            raise ValidationError({'account': 'Select an active asset account.'})
        book_balance = self._book_balance(branch_id, account.pk, as_of_date)
        reconciliation = AccountReconciliation(
            branch_id=branch_id,
            account=account,
            as_of_date=as_of_date,
            statement_balance=statement_balance,
            book_balance=book_balance,
            variance=statement_balance - book_balance,
            notes=notes.strip(),
            prepared_by=self.request.user,
        )
        reconciliation.full_clean()
        reconciliation.save()
        log_action(
            'Create',
            'AccountReconciliation',
            reconciliation.pk,
            new_values={
                'account_id': account.pk,
                'as_of_date': as_of_date.isoformat(),
                'variance': str(reconciliation.variance),
            },
            branch_id=branch_id,
        )
        return reconciliation

    @transaction.atomic
    def confirm(self, *, reconciliation_id):
        reconciliation = AccountReconciliation.objects.select_for_update().filter(pk=reconciliation_id).first()
        if reconciliation is None:
            raise AccountReconciliation.DoesNotExist
        self._ensure_branch_access(reconciliation.branch_id)
        if not Branch.unscoped.select_for_update().filter(
            pk=reconciliation.branch_id,
            is_active=True,
        ).exists():
            raise ValidationError({'branch': 'The reconciliation branch is not active.'})
        if reconciliation.status != AccountReconciliation.STATUS_OPEN:
            raise ValidationError('This reconciliation has already been confirmed.')
        reconciliation.book_balance = self._book_balance(
            reconciliation.branch_id,
            reconciliation.account_id,
            reconciliation.as_of_date,
        )
        reconciliation.variance = reconciliation.statement_balance - reconciliation.book_balance
        if reconciliation.variance != ZERO and not reconciliation.notes.strip():
            raise ValidationError({'notes': 'Explain the variance before confirming this reconciliation.'})
        reconciliation.status = AccountReconciliation.STATUS_RECONCILED
        reconciliation.reconciled_by = self.request.user
        reconciliation.reconciled_at = timezone.now()
        reconciliation.full_clean()
        reconciliation._reconciliation_authorized = True
        try:
            reconciliation.save(update_fields=[
                'book_balance',
                'variance',
                'status',
                'reconciled_by',
                'reconciled_at',
            ])
        finally:
            del reconciliation._reconciliation_authorized
        log_action(
            'Reconcile',
            'AccountReconciliation',
            reconciliation.pk,
            new_values={
                'status': reconciliation.status,
                'variance': str(reconciliation.variance),
            },
            branch_id=reconciliation.branch_id,
        )
        return reconciliation

    def _ensure_branch_access(self, branch_id):
        user = self.request.user
        if (
            not user.is_authenticated
            or not user.is_active
            or branch_id not in user.accessible_branch_ids(
                getattr(self.request, 'active_branch_id', None)
            )
        ):
            raise ValidationError({'branch': 'You cannot access this branch.'})

    @staticmethod
    def _book_balance(branch_id, account_id, as_of_date):
        totals = JournalLine.objects.filter(
            account_id=account_id,
            entry__branch_id=branch_id,
            entry__status=JournalEntry.STATUS_POSTED,
            entry__journal_date__lte=as_of_date,
        ).aggregate(debit=Sum('debit'), credit=Sum('credit'))
        return (totals['debit'] or ZERO) - (totals['credit'] or ZERO)
