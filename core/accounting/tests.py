import uuid
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import RequestFactory, TestCase
from django.urls import reverse

from core.accounts.models import Permission, Role, RolePermission, UserRole
from core.accounts.permission_utils import sync_permissions
from core.branch.models import Branch

from .models import (
    Account,
    AccountingPeriod,
    AccountReconciliation,
    FiscalYear,
    JournalEntry,
    JournalLine,
    SystemAccountMapping,
)
from .services import JournalService, ReconciliationService, build_trial_balance


class JournalServiceTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name='Accounting Branch', code='ACC')
        self.user = get_user_model().objects.create_user(
            username='accounting-maker',
            password='A-strong-test-password-123',  # nosec B106 - isolated test account
            branch=self.branch,
        )
        self.request = RequestFactory().post('/accounting/journal-entries/')
        self.request.user = self.user
        self.request.active_branch_id = None
        self.service = JournalService(self.request)
        self.fiscal_year = FiscalYear.objects.create(
            name='FY 2025',
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
        )
        self.period = AccountingPeriod.objects.create(
            fiscal_year=self.fiscal_year,
            number=1,
            name='Annual test period',
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
        )
        self.cash = Account.objects.create(
            code='1000',
            name='Cash',
            account_type=Account.ASSET,
            normal_balance=Account.DEBIT,
        )
        self.income = Account.objects.create(
            code='4000',
            name='Interest income',
            account_type=Account.INCOME,
            normal_balance=Account.CREDIT,
        )

    def create_balanced_entry(self, requires_approval=False):
        entry = self.service.create_entry(
            branch_id=self.branch.pk,
            journal_date=date(2025, 2, 1),
            narration='Test posting',
            requires_approval=requires_approval,
        )
        self.service.add_line(
            entry_id=entry.pk,
            account_id=self.cash.pk,
            debit=Decimal('125.50'),
        )
        self.service.add_line(
            entry_id=entry.pk,
            account_id=self.income.pk,
            credit=Decimal('125.50'),
        )
        return entry

    def test_posting_requires_balanced_lines_and_closed_periods_are_rejected(self):
        entry = self.service.create_entry(
            branch_id=self.branch.pk,
            journal_date=date(2025, 2, 1),
            narration='Unbalanced entry',
        )
        self.service.add_line(
            entry_id=entry.pk,
            account_id=self.cash.pk,
            debit=Decimal('100.00'),
        )
        with self.assertRaises(ValidationError):
            self.service.post(entry_id=entry.pk)

        self.period.is_closed = True
        self.period.save(update_fields=['is_closed'])
        with self.assertRaises(ValidationError):
            self.service.create_entry(
                branch_id=self.branch.pk,
                journal_date=date(2025, 2, 1),
                narration='Closed period entry',
            )

    def test_posted_journal_is_immutable_and_trial_balance_balances(self):
        entry = self.create_balanced_entry()
        posted = self.service.post(entry_id=entry.pk)

        self.assertEqual(posted.status, JournalEntry.STATUS_POSTED)
        with self.assertRaises(TypeError):
            posted.save()
        with self.assertRaises(TypeError):
            JournalLine.objects.filter(entry=posted).update(narration='Changed')
        with self.assertRaises(TypeError):
            JournalLine.objects.filter(entry=posted).delete()
        with self.assertRaises(TypeError):
            JournalEntry.unscoped.filter(pk=posted.pk).update(status=JournalEntry.STATUS_DRAFT)

        report = build_trial_balance(
            start_date=date(2025, 2, 1),
            end_date=date(2025, 2, 28),
            branch_ids={self.branch.pk},
        )
        self.assertEqual(report['totals']['debit'], Decimal('125.50'))
        self.assertEqual(report['totals']['credit'], Decimal('125.50'))
        self.assertEqual(report['totals']['closing_debit'], Decimal('125.50'))
        self.assertEqual(report['totals']['closing_credit'], Decimal('125.50'))

    def test_posted_status_cannot_be_set_outside_the_journal_service(self):
        entry = self.create_balanced_entry()
        entry.status = JournalEntry.STATUS_POSTED
        entry.posted_by = self.user
        with self.assertRaises(TypeError):
            entry.save()
        with self.assertRaises(TypeError):
            JournalEntry.unscoped.filter(pk=entry.pk).update(status=JournalEntry.STATUS_POSTED)

    def test_reversal_posts_equal_opposite_lines_and_only_once(self):
        entry = self.create_balanced_entry()
        self.service.post(entry_id=entry.pk)

        reversal = self.service.reverse(
            entry_id=entry.pk,
            reversal_date=date(2025, 3, 1),
            reason='Correction',
        )

        self.assertEqual(reversal.status, JournalEntry.STATUS_POSTED)
        self.assertEqual(reversal.reversal_of_id, entry.pk)
        self.assertEqual(
            list(reversal.lines.order_by('account_id').values_list('debit', 'credit')),
            [(Decimal('0.00'), Decimal('125.50')), (Decimal('125.50'), Decimal('0.00'))],
        )
        with self.assertRaises(ValidationError):
            self.service.reverse(
                entry_id=entry.pk,
                reversal_date=date(2025, 3, 2),
                reason='Duplicate correction',
            )

    def test_approval_requires_a_different_user(self):
        entry = self.create_balanced_entry(requires_approval=True)
        self.service.submit_for_approval(entry_id=entry.pk)

        with self.assertRaises(ValidationError):
            self.service.post(entry_id=entry.pk)

        checker = get_user_model().objects.create_user(
            username='accounting-checker',
            password='A-strong-test-password-124',
            branch=self.branch,
        )
        self.request.user = checker
        posted = JournalService(self.request).post(entry_id=entry.pk)
        self.assertEqual(posted.posted_by_id, checker.pk)

    def test_journal_create_reuses_an_idempotency_key(self):
        idempotency_key = uuid.uuid4()
        original = self.service.create_entry(
            branch_id=self.branch.pk,
            journal_date=date(2025, 2, 1),
            narration='Idempotent entry',
            idempotency_key=idempotency_key,
        )
        replay = self.service.create_entry(
            branch_id=self.branch.pk,
            journal_date=date(2025, 2, 1),
            narration='Idempotent entry',
            idempotency_key=idempotency_key,
        )

        self.assertEqual(replay.pk, original.pk)
        self.assertTrue(replay._idempotent_replay)

    def test_reconciliation_requires_variance_notes_and_blocks_backdating(self):
        entry = self.create_balanced_entry()
        self.service.post(entry_id=entry.pk)
        reconciliation_service = ReconciliationService(self.request)
        reconciliation = reconciliation_service.create(
            branch_id=self.branch.pk,
            account_id=self.cash.pk,
            as_of_date=date(2025, 2, 1),
            statement_balance=Decimal('130.00'),
        )

        with self.assertRaises(ValidationError):
            reconciliation_service.confirm(reconciliation_id=reconciliation.pk)

        reconciliation.notes = 'Cash count variance documented.'
        reconciliation.save(update_fields=['notes'])
        confirmed = reconciliation_service.confirm(reconciliation_id=reconciliation.pk)
        self.assertEqual(confirmed.status, AccountReconciliation.STATUS_RECONCILED)
        self.assertEqual(confirmed.variance, Decimal('4.50'))

        backdated = self.create_balanced_entry()
        with self.assertRaises(ValidationError):
            self.service.post(entry_id=backdated.pk)

        with self.assertRaises(TypeError):
            confirmed.save()
        with self.assertRaises(TypeError):
            AccountReconciliation.objects.filter(pk=confirmed.pk).delete()

    def test_system_account_mapping_requires_the_correct_account_type(self):
        mapping = SystemAccountMapping(key='member_savings', account=self.cash)

        with self.assertRaises(ValidationError):
            mapping.full_clean()


class AccountingViewTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name='View Branch', code='VIEW')
        self.user = get_user_model().objects.create_user(
            username='accounting-viewer',
            password='A-strong-test-password-125',
            branch=self.branch,
        )
        self.fiscal_year = FiscalYear.objects.create(
            name='View FY 2025',
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
        )
        self.period = AccountingPeriod.objects.create(
            fiscal_year=self.fiscal_year,
            number=1,
            name='Annual period',
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
        )
        self.cash = Account.objects.create(
            code='1100',
            name='Cash on hand',
            account_type=Account.ASSET,
            normal_balance=Account.DEBIT,
        )
        self.income = Account.objects.create(
            code='4100',
            name='Service income',
            account_type=Account.INCOME,
            normal_balance=Account.CREDIT,
        )
        sync_permissions()
        role = Role.objects.create(name='Accounting view role')
        route_names = [
            'Module_Accounting_account_list',
            'Module_Accounting_fiscal_years',
            'Module_Accounting_journal_add',
            'Module_Accounting_journal_detail',
            'Module_Accounting_journal_post',
            'Module_Accounting_trial_balance',
            'Module_Accounting_system_accounts',
            'Module_Accounting_reconciliation_list',
            'Module_Accounting_period_close',
        ]
        for route_name in route_names:
            permission = Permission.objects.get(route_name=route_name)
            RolePermission.objects.create(role=role, permission=permission)
        UserRole.objects.create(user=self.user, role=role)
        self.client.force_login(self.user)

    def test_accounting_screens_render(self):
        account_response = self.client.get(reverse('accounting:Module_Accounting_account_list'))
        fiscal_response = self.client.get(reverse('accounting:Module_Accounting_fiscal_years'))
        mapping_response = self.client.get(reverse('accounting:Module_Accounting_system_accounts'))
        reconciliation_response = self.client.get(
            reverse('accounting:Module_Accounting_reconciliation_list')
        )

        self.assertEqual(account_response.status_code, 200)
        self.assertContains(account_response, 'Chart of accounts')
        self.assertEqual(fiscal_response.status_code, 200)
        self.assertContains(fiscal_response, 'Annual period')
        self.assertEqual(mapping_response.status_code, 200)
        self.assertEqual(reconciliation_response.status_code, 200)

    def test_accounting_navigation_is_permission_aware(self):
        response = self.client.get('/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Accounting')

    def test_period_close_route_is_post_only(self):
        response = self.client.get(
            reverse('accounting:Module_Accounting_period_close', args=[self.period.pk])
        )

        self.assertEqual(response.status_code, 405)

    def test_journal_form_saves_only_a_balanced_voucher(self):
        response = self.client.post(reverse('accounting:Module_Accounting_journal_add'), {
            'idempotency_key': str(uuid.uuid4()),
            'branch': str(self.branch.pk),
            'journal_date': '2025-02-01',
            'voucher_type': 'journal',
            'narration': 'Opening service income',
            'requires_approval': '',
            'lines-TOTAL_FORMS': '2',
            'lines-INITIAL_FORMS': '0',
            'lines-MIN_NUM_FORMS': '2',
            'lines-MAX_NUM_FORMS': '1000',
            'lines-0-account': str(self.cash.pk),
            'lines-0-debit': '200.00',
            'lines-0-credit': '0.00',
            'lines-0-narration': '',
            'lines-1-account': str(self.income.pk),
            'lines-1-debit': '0.00',
            'lines-1-credit': '200.00',
            'lines-1-narration': '',
        })

        self.assertEqual(response.status_code, 302)
        entry = JournalEntry.unscoped.get()
        self.assertEqual(entry.lines.count(), 2)
        self.assertEqual(entry.status, JournalEntry.STATUS_DRAFT)

    def test_unbalanced_journal_form_does_not_create_an_entry(self):
        response = self.client.post(reverse('accounting:Module_Accounting_journal_add'), {
            'idempotency_key': str(uuid.uuid4()),
            'branch': str(self.branch.pk),
            'journal_date': '2025-02-01',
            'voucher_type': 'journal',
            'narration': 'Unbalanced voucher',
            'lines-TOTAL_FORMS': '2',
            'lines-INITIAL_FORMS': '0',
            'lines-MIN_NUM_FORMS': '2',
            'lines-MAX_NUM_FORMS': '1000',
            'lines-0-account': str(self.cash.pk),
            'lines-0-debit': '200.00',
            'lines-0-credit': '0.00',
            'lines-1-account': str(self.income.pk),
            'lines-1-debit': '0.00',
            'lines-1-credit': '150.00',
        })

        self.assertEqual(response.status_code, 400)
        self.assertFalse(JournalEntry.unscoped.exists())

    def test_trial_balance_screen_reports_period_totals(self):
        request = RequestFactory().post('/accounting/journal-entries/')
        request.user = self.user
        request.active_branch_id = None
        service = JournalService(request)
        entry = service.create_entry(
            branch_id=self.branch.pk,
            journal_date=date(2025, 2, 1),
            narration='Trial balance entry',
        )
        service.add_line(
            entry_id=entry.pk,
            account_id=self.cash.pk,
            debit=Decimal('300.00'),
        )
        service.add_line(
            entry_id=entry.pk,
            account_id=self.income.pk,
            credit=Decimal('300.00'),
        )
        service.post(entry_id=entry.pk)

        response = self.client.get(reverse('accounting:Module_Accounting_trial_balance'), {
            'start_date': '2025-02-01',
            'end_date': '2025-02-28',
            'branch': str(self.branch.pk),
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '300.00')
