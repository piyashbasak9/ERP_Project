import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from pathlib import Path
from threading import Barrier

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import DatabaseError, close_old_connections, connection, transaction
from django.test import RequestFactory, SimpleTestCase, TestCase, TransactionTestCase
from django.urls import reverse

from core.accounting.models import (
    Account,
    AccountingPeriod,
    FiscalYear,
    JournalEntry,
    JournalLine,
    SystemAccountMapping,
)
from core.accounts.models import Permission, Role, RolePermission, UserRole
from core.accounts.permission_utils import get_all_urls
from core.audit.models import AuditLog
from core.branch.models import Branch, Group, Member
from core.common.context import current_branch_id_var, current_user_var

from .models import SavingsAccount, SavingsProduct, SavingsTransaction
from .services import SavingsService


class SavingsRoutePermissionTests(SimpleTestCase):
    def test_savings_routes_are_registered_for_explicit_permissions(self):
        routes = {route["route_name"] for route in get_all_urls()}
        savings_routes = {name for name in routes if name.startswith("Module_Savings_")}
        self.assertIn("Module_Savings_accounts", savings_routes)
        self.assertIn("Module_Savings_approve_withdrawal", savings_routes)
        self.assertIn("Module_Savings_reverse", savings_routes)
        self.assertIn("Module_Savings_balance_report", savings_routes)


class SavingsServiceTests(TestCase):
    def setUp(self):
        self.branch = Branch.unscoped.create(name="Savings Branch", code="SAV")
        self.user = get_user_model().objects.create_user(
            username="savings-maker",
            password="A-strong-test-password-123",
            branch=self.branch,
        )
        self.request = RequestFactory().post("/savings/transactions/")
        self.request.user = self.user
        self.request.active_branch_id = None
        self.service = SavingsService(self.request)

        self.fiscal_year = FiscalYear.objects.create(
            name="Savings FY 2025",
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
        )
        AccountingPeriod.objects.create(
            fiscal_year=self.fiscal_year,
            number=1,
            name="January",
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 31),
        )

        self.cash = self._account("1100", "Cash", Account.ASSET, Account.DEBIT)
        self.bank = self._account("1110", "Bank", Account.ASSET, Account.DEBIT)
        self.savings_ledger = self._account(
            "2100", "Member savings", Account.LIABILITY, Account.CREDIT
        )
        self.interest_expense = self._account(
            "5100", "Savings interest expense", Account.EXPENSE, Account.DEBIT
        )
        self.fee_income = self._account(
            "4100", "Fee income", Account.INCOME, Account.CREDIT
        )
        self.tax_payable = self._account(
            "2200", "Withholding tax", Account.LIABILITY, Account.CREDIT
        )
        for key, account in [
            ("cash_in_hand", self.cash),
            ("bank_accounts", self.bank),
            ("member_savings", self.savings_ledger),
            ("interest_expense", self.interest_expense),
            ("fee_income", self.fee_income),
            ("withholding_tax_payable", self.tax_payable),
        ]:
            SystemAccountMapping.objects.create(key=key, account=account)

        self.product = SavingsProduct.objects.create(
            code="GEN",
            name="General savings",
            savings_type=SavingsProduct.TYPE_GENERAL,
            annual_interest_rate=Decimal("0.365000"),
            posting_frequency=SavingsProduct.FREQUENCY_MONTHLY,
            minimum_opening_balance=Decimal("10.00"),
            minimum_balance=Decimal("0.00"),
            fee_amount=Decimal("2.50"),
            withdrawal_approval_threshold=Decimal("50.00"),
            withholding_tax_rate=Decimal("0.100000"),
        )
        self.member = Member.unscoped.create(
            branch=self.branch,
            member_code="SAV-0001",
            first_name="Amina",
            last_name="Begum",
            status=Member.STATUS_ACTIVE,
        )

    @staticmethod
    def _account(code, name, account_type, normal_balance):
        return Account.objects.create(
            code=code,
            name=name,
            account_type=account_type,
            normal_balance=normal_balance,
        )

    def open_account(self, *, opening_balance=Decimal("100.00"), key=None):
        return self.service.open_account(
            branch_id=self.branch.pk,
            product_id=self.product.pk,
            member_id=self.member.pk,
            opened_at=date(2025, 1, 1),
            opening_balance=opening_balance,
            idempotency_key=key or uuid.uuid4(),
        )

    def test_opening_account_and_deposit_are_idempotent_and_ledger_posted(self):
        open_key = uuid.uuid4()
        account = self.open_account(key=open_key)
        self.assertEqual(account.balance, Decimal("100.00"))
        replayed_account = self.open_account(key=open_key)
        self.assertEqual(replayed_account.pk, account.pk)
        self.assertTrue(replayed_account._idempotent_replay)
        with self.assertRaises(ValidationError):
            self.open_account(key=open_key, opening_balance=Decimal("125.00"))

        transaction_key = uuid.uuid4()
        first = self.service.deposit(
            account_id=account.pk,
            amount=Decimal("25.00"),
            transaction_date=date(2025, 1, 2),
            payment_channel=SavingsTransaction.CHANNEL_BANK,
            idempotency_key=transaction_key,
        )
        replay = self.service.deposit(
            account_id=account.pk,
            amount=Decimal("25.00"),
            transaction_date=date(2025, 1, 2),
            payment_channel=SavingsTransaction.CHANNEL_BANK,
            idempotency_key=transaction_key,
        )

        account.refresh_from_db()
        self.assertEqual(first.pk, replay.pk)
        self.assertEqual(account.balance, Decimal("125.00"))
        self.assertEqual(first.journal_entry.status, JournalEntry.STATUS_POSTED)
        self.assertEqual(first.journal_entry.lines.count(), 2)

    def test_withdrawal_reserves_funds_requires_different_checker_and_posts(self):
        account = self.open_account()
        pending = self.service.withdraw(
            account_id=account.pk,
            amount=Decimal("60.00"),
            transaction_date=date(2025, 1, 2),
            payment_channel=SavingsTransaction.CHANNEL_CASH,
            idempotency_key=uuid.uuid4(),
        )
        account.refresh_from_db()
        self.assertEqual(pending.status, SavingsTransaction.STATUS_PENDING)
        self.assertEqual(account.reserved_balance, Decimal("60.00"))
        self.assertEqual(account.available_balance, Decimal("40.00"))

        with self.assertRaises(ValidationError):
            self.service.approve_withdrawal(transaction_id=pending.pk)

        checker = get_user_model().objects.create_user(
            username="savings-checker",
            password="A-strong-test-password-124",
            branch=self.branch,
        )
        self.request.user = checker
        posted = SavingsService(self.request).approve_withdrawal(
            transaction_id=pending.pk
        )
        account.refresh_from_db()
        self.assertEqual(posted.status, SavingsTransaction.STATUS_POSTED)
        self.assertEqual(account.balance, Decimal("40.00"))
        self.assertEqual(account.reserved_balance, Decimal("0.00"))
        self.assertEqual(posted.approved_by_id, checker.pk)

    def test_rejecting_withdrawal_releases_reservation(self):
        account = self.open_account()
        pending = self.service.withdraw(
            account_id=account.pk,
            amount=Decimal("60.00"),
            transaction_date=date(2025, 1, 2),
            payment_channel=SavingsTransaction.CHANNEL_CASH,
            idempotency_key=uuid.uuid4(),
        )
        with self.assertRaises(ValidationError):
            self.service.reject_withdrawal(
                transaction_id=pending.pk,
                reason="Maker cannot approve their own request.",
            )
        checker = get_user_model().objects.create_user(
            username="savings-reject-checker",
            password="A-strong-test-password-126",
            branch=self.branch,
        )
        self.request.user = checker
        rejected = SavingsService(self.request).reject_withdrawal(
            transaction_id=pending.pk,
            reason="Supporting document is missing.",
        )
        account.refresh_from_db()
        self.assertEqual(rejected.status, SavingsTransaction.STATUS_REJECTED)
        self.assertEqual(account.balance, Decimal("100.00"))
        self.assertEqual(account.reserved_balance, Decimal("0.00"))
        self.assertEqual(rejected.rejected_by_id, checker.pk)

    def test_withdrawal_cannot_breach_available_balance_or_product_minimum(self):
        account = self.open_account()
        with self.assertRaises(ValidationError):
            self.service.withdraw(
                account_id=account.pk,
                amount=Decimal("100.01"),
                transaction_date=date(2025, 1, 2),
                payment_channel=SavingsTransaction.CHANNEL_CASH,
                idempotency_key=uuid.uuid4(),
            )
        account.refresh_from_db()
        self.assertEqual(account.balance, Decimal("100.00"))

    def test_reversal_posts_opposite_journal_and_restores_savings_balance(self):
        account = self.open_account()
        deposit = self.service.deposit(
            account_id=account.pk,
            amount=Decimal("20.00"),
            transaction_date=date(2025, 1, 2),
            payment_channel=SavingsTransaction.CHANNEL_CASH,
            idempotency_key=uuid.uuid4(),
        )
        reversal = self.service.reverse(
            transaction_id=deposit.pk,
            reversal_date=date(2025, 1, 3),
            reason="Incorrect deposit amount.",
        )
        account.refresh_from_db()
        self.assertEqual(reversal.transaction_type, SavingsTransaction.TYPE_REVERSAL)
        self.assertEqual(reversal.journal_entry.status, JournalEntry.STATUS_POSTED)
        self.assertEqual(account.balance, Decimal("100.00"))

        with self.assertRaises(ValidationError):
            self.service.reverse(
                transaction_id=deposit.pk,
                reversal_date=date(2025, 1, 4),
                reason="Duplicate reversal.",
            )

    def test_reversal_adds_counter_entry_without_changing_original(self):
        account = self.open_account()
        original = self.service.deposit(
            account_id=account.pk,
            amount=Decimal("20.00"),
            transaction_date=date(2025, 1, 2),
            payment_channel=SavingsTransaction.CHANNEL_CASH,
            idempotency_key=uuid.uuid4(),
        )
        before = (
            original.amount,
            original.balance_before,
            original.balance_after,
            original.status,
            original.journal_entry_id,
            tuple(
                original.journal_entry.lines.values_list(
                    "account_id", "debit", "credit"
                )
            ),
        )
        reversal = self.service.reverse(
            transaction_id=original.pk,
            reversal_date=date(2025, 1, 3),
            reason="Counter-entry verification.",
        )
        original.refresh_from_db()
        after = (
            original.amount,
            original.balance_before,
            original.balance_after,
            original.status,
            original.journal_entry_id,
            tuple(
                original.journal_entry.lines.values_list(
                    "account_id", "debit", "credit"
                )
            ),
        )
        self.assertEqual(after, before)
        self.assertEqual(reversal.reversal_of_id, original.pk)
        self.assertEqual(
            reversal.journal_entry.reversal_of_id, original.journal_entry_id
        )

    def test_missing_system_mapping_rolls_back_all_posting_data(self):
        account = self.open_account()
        SystemAccountMapping.objects.filter(key="member_savings").delete()
        transaction_count = SavingsTransaction.unscoped.count()
        journal_count = JournalEntry.unscoped.count()
        with self.assertRaisesMessage(ValidationError, "member_savings"):
            self.service.deposit(
                account_id=account.pk,
                amount=Decimal("10.00"),
                transaction_date=date(2025, 1, 2),
                payment_channel=SavingsTransaction.CHANNEL_CASH,
                idempotency_key=uuid.uuid4(),
            )
        account.refresh_from_db()
        self.assertEqual(account.balance, Decimal("100.00"))
        self.assertEqual(SavingsTransaction.unscoped.count(), transaction_count)
        self.assertEqual(JournalEntry.unscoped.count(), journal_count)

    def test_interest_golden_formula_uses_actual_365_and_half_up_rounding(self):
        account = self.open_account(opening_balance=Decimal("10.00"))
        self.product.annual_interest_rate = Decimal("0.182500")
        self.product.save(update_fields=["annual_interest_rate"])
        self.assertEqual(
            self.service.calculate_interest(
                account_id=account.pk,
                start_date=date(2025, 1, 1),
                end_date=date(2025, 1, 1),
            ),
            Decimal("0.01"),
        )

    def test_interest_daily_balance_golden_example_sums_each_calendar_day(self):
        account = self.open_account()
        self.service.deposit(
            account_id=account.pk,
            amount=Decimal("100.00"),
            transaction_date=date(2025, 1, 2),
            payment_channel=SavingsTransaction.CHANNEL_CASH,
            idempotency_key=uuid.uuid4(),
        )
        self.assertEqual(
            self.service.calculate_interest(
                account_id=account.pk,
                start_date=date(2025, 1, 1),
                end_date=date(2025, 1, 2),
            ),
            Decimal("0.30"),
        )

    def test_savings_reconciliation_matches_member_savings_ledger(self):
        self.open_account()
        result = self.service.reconcile_savings(
            as_of_date=date(2025, 1, 31),
            branch_id=self.branch.pk,
        )
        self.assertEqual(result["subledger_balance"], Decimal("100.00"))
        self.assertEqual(result["ledger_balance"], Decimal("100.00"))
        self.assertEqual(result["variance"], Decimal("0.00"))
        self.assertTrue(result["is_reconciled"])

    def test_dormancy_requires_configured_inactivity_and_reactivation_is_audited(self):
        self.product.dormant_after_days = 10
        self.product.save(update_fields=["dormant_after_days"])
        account = self.open_account()
        self.assertEqual(
            self.service.mark_dormant_accounts(as_of_date=date(2025, 1, 10)),
            [],
        )
        dormant = self.service.mark_dormant_accounts(as_of_date=date(2025, 1, 11))
        account.refresh_from_db()
        self.assertEqual([item.pk for item in dormant], [account.pk])
        self.assertEqual(account.status, SavingsAccount.STATUS_DORMANT)
        self.assertEqual(
            self.service.calculate_interest(
                account_id=account.pk,
                start_date=date(2025, 1, 1),
                end_date=date(2025, 1, 31),
            ),
            Decimal("0.00"),
        )
        self.service.reactivate_account(
            account_id=account.pk, reason="Member requested reactivation."
        )
        account.refresh_from_db()
        self.assertEqual(account.status, SavingsAccount.STATUS_ACTIVE)
        self.assertTrue(
            AuditLog.objects.filter(
                action="Reactivate",
                entity_name="SavingsAccount",
                entity_id=str(account.pk),
                remarks="Member requested reactivation.",
            ).exists()
        )

    def test_dormant_product_can_explicitly_continue_interest(self):
        self.product.dormant_after_days = 10
        self.product.pays_interest_when_dormant = True
        self.product.save(
            update_fields=["dormant_after_days", "pays_interest_when_dormant"]
        )
        account = self.open_account()
        self.service.mark_dormant_accounts(as_of_date=date(2025, 1, 11))
        self.assertEqual(
            self.service.calculate_interest(
                account_id=account.pk,
                start_date=date(2025, 1, 1),
                end_date=date(2025, 1, 31),
            ),
            Decimal("3.10"),
        )

    def test_posted_journal_and_savings_rows_are_immutable_in_django_and_postgres(self):
        self.open_account()
        savings_transaction = SavingsTransaction.unscoped.order_by("pk").first()
        journal = savings_transaction.journal_entry
        line = journal.lines.first()
        with self.assertRaises(TypeError):
            savings_transaction.save()
        with self.assertRaises(TypeError):
            savings_transaction.delete()
        with self.assertRaises(TypeError):
            SavingsTransaction.unscoped.filter(pk=savings_transaction.pk).update(
                narration="edited"
            )
        with self.assertRaises(TypeError):
            journal.save()
        with self.assertRaises(TypeError):
            JournalEntry.unscoped.filter(pk=journal.pk).update(narration="edited")
        with self.assertRaises(TypeError):
            line.save()
        with self.assertRaises(TypeError):
            JournalLine.objects.filter(pk=line.pk).update(narration="edited")
        self.assertEqual(connection.vendor, "postgresql")
        for sql, params in [
            (
                "UPDATE savings_transactions SET narration = %s WHERE id = %s",
                ["edited", savings_transaction.pk],
            ),
            (
                "DELETE FROM savings_transactions WHERE id = %s",
                [savings_transaction.pk],
            ),
            (
                "UPDATE accounting_journal_entries SET narration = %s WHERE id = %s",
                ["edited", journal.pk],
            ),
            ("DELETE FROM accounting_journal_entries WHERE id = %s", [journal.pk]),
            (
                "UPDATE accounting_journal_lines SET narration = %s WHERE id = %s",
                ["edited", line.pk],
            ),
            ("DELETE FROM accounting_journal_lines WHERE id = %s", [line.pk]),
        ]:
            with (
                self.subTest(sql=sql),
                self.assertRaises(DatabaseError),
                transaction.atomic(),connection.cursor() as cursor
            ):
                cursor.execute(sql, params)

    def test_runtime_role_cannot_mutate_posted_financial_records(self):
        self.open_account()
        savings_transaction = SavingsTransaction.unscoped.order_by("pk").first()
        journal = savings_transaction.journal_entry
        line = journal.lines.first()
        database_dir = Path(__file__).resolve().parents[2] / "database"

        with connection.cursor() as cursor:
            cursor.execute("GRANT USAGE ON SCHEMA public TO erp_runtime")
            cursor.execute(
                "GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA public TO erp_runtime"
            )
            cursor.execute(
                "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO erp_runtime"
            )
            cursor.execute(
                (database_dir / "savings_runtime_role.sql").read_text(
                    encoding="utf-8"
                )
            )
            cursor.execute("SET ROLE erp_runtime")
            try:
                cursor.execute(
                    "SELECT has_column_privilege("
                    "'erp_runtime', 'savings_transactions', 'status', 'UPDATE'), "
                    "has_column_privilege("
                    "'erp_runtime', 'savings_transactions', 'narration', 'UPDATE')"
                )
                status_update, narration_update = cursor.fetchone()
                self.assertTrue(status_update)
                self.assertFalse(narration_update)

                for sql, params in [
                    (
                        "UPDATE savings_transactions SET status = %s WHERE id = %s",
                        ["pending", savings_transaction.pk],
                    ),
                    (
                        "DELETE FROM savings_transactions WHERE id = %s",
                        [savings_transaction.pk],
                    ),
                    (
                        "UPDATE accounting_journal_entries "
                        + "SET status = %s WHERE id = %s",
                        ["draft", journal.pk],
                    ),
                    (
                        "DELETE FROM accounting_journal_entries WHERE id = %s",
                        [journal.pk],
                    ),
                    (
                        "UPDATE accounting_journal_lines "
                        + "SET narration = %s WHERE id = %s",
                        ["edited", line.pk],
                    ),
                    (
                        "DELETE FROM accounting_journal_lines WHERE id = %s",
                        [line.pk],
                    ),
                ]:
                    with (
                        self.subTest(sql=sql),
                        self.assertRaises(DatabaseError),
                        transaction.atomic(),
                    ):
                        cursor.execute(sql, params)
            finally:
                cursor.execute("RESET ROLE")

    def test_interest_uses_daily_balances_and_posts_tax_in_the_same_ledger_entry(self):
        account = self.open_account()
        self.service.deposit(
            account_id=account.pk,
            amount=Decimal("200.00"),
            transaction_date=date(2025, 1, 16),
            payment_channel=SavingsTransaction.CHANNEL_CASH,
            idempotency_key=uuid.uuid4(),
        )

        interest = self.service.post_interest(
            account_id=account.pk,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 31),
            idempotency_key=uuid.uuid4(),
        )
        account.refresh_from_db()

        self.assertEqual(interest.gross_amount, Decimal("6.30"))
        self.assertEqual(interest.tax_amount, Decimal("0.63"))
        self.assertEqual(interest.amount, Decimal("5.67"))
        self.assertEqual(account.balance, Decimal("305.67"))
        self.assertEqual(interest.journal_entry.lines.count(), 3)

    def test_product_fee_posts_against_savings_and_income(self):
        account = self.open_account()
        fee = self.service.charge_fee(
            account_id=account.pk,
            transaction_date=date(2025, 1, 2),
            idempotency_key=uuid.uuid4(),
        )
        account.refresh_from_db()
        self.assertEqual(fee.transaction_type, SavingsTransaction.TYPE_FEE)
        self.assertEqual(fee.amount, Decimal("2.50"))
        self.assertEqual(account.balance, Decimal("97.50"))
        self.assertEqual(fee.journal_entry.lines.count(), 2)

    def test_group_account_tracks_each_member_contribution(self):
        group = Group.objects.create(
            branch=self.branch,
            name="North Group",
            code="NORTH-1",
        )
        self.member.group = group
        self.member.save()
        account = self.service.open_account(
            branch_id=self.branch.pk,
            product_id=self.product.pk,
            group_id=group.pk,
            contribution_member_id=self.member.pk,
            opened_at=date(2025, 1, 1),
            opening_balance=Decimal("100.00"),
            idempotency_key=uuid.uuid4(),
        )
        opening = SavingsTransaction.unscoped.get(account=account)
        self.assertEqual(opening.contribution_member_id, self.member.pk)
        self.assertEqual(account.group_id, group.pk)

    def test_sequential_account_numbers_and_closing_zero_balance_account(self):
        first = self.open_account()
        second = self.open_account()
        self.assertTrue(first.account_number.endswith("000001"))
        self.assertTrue(second.account_number.endswith("000002"))

        self.product.withdrawal_approval_threshold = None
        self.product.save(update_fields=["withdrawal_approval_threshold"])
        self.service.withdraw(
            account_id=first.pk,
            amount=Decimal("100.00"),
            transaction_date=date(2025, 1, 2),
            payment_channel=SavingsTransaction.CHANNEL_CASH,
            idempotency_key=uuid.uuid4(),
        )
        closed = self.service.close_account(account_id=first.pk)
        self.assertEqual(closed.status, SavingsAccount.STATUS_CLOSED)
        self.assertEqual(closed.balance, Decimal("0.00"))

    def test_savings_transactions_are_branch_scoped_and_immutable(self):
        account = self.open_account()
        entry = SavingsTransaction.unscoped.get(account=account)
        token_user = current_user_var.set(self.user)
        token_branch = current_branch_id_var.set(None)
        try:
            self.assertTrue(SavingsTransaction.objects.filter(pk=entry.pk).exists())
        finally:
            current_branch_id_var.reset(token_branch)
            current_user_var.reset(token_user)
        with self.assertRaises(TypeError):
            entry.save()
        with self.assertRaises(TypeError):
            SavingsTransaction.unscoped.filter(pk=entry.pk).update(narration="Edited")
        account.balance = Decimal("999.00")
        with self.assertRaises(TypeError):
            account.save()
        with self.assertRaises(TypeError):
            SavingsAccount.unscoped.filter(pk=account.pk).update(
                balance=Decimal("999.00")
            )
        with self.assertRaises(TypeError):
            account.delete()


class SavingsViewTests(TestCase):
    def setUp(self):
        self.branch = Branch.unscoped.create(name="Savings UI Branch", code="SUI")
        self.user = get_user_model().objects.create_superuser(
            username="savings-ui-admin",
            password="A-strong-test-password-125",
            branch=self.branch,
        )
        self.product = SavingsProduct.objects.create(
            code="UI-GEN",
            name="UI general savings",
            savings_type=SavingsProduct.TYPE_GENERAL,
            minimum_opening_balance=Decimal("0.00"),
        )
        self.client.force_login(self.user)
        self.request = RequestFactory().post("/savings/accounts/")
        self.request.user = self.user
        self.request.active_branch_id = None

    def test_savings_pages_and_popup_forms_render(self):
        names = [
            "Module_Savings_products",
            "Module_Savings_accounts",
            "Module_Savings_transactions",
            "Module_Savings_balance_report",
        ]
        for route_name in names:
            with self.subTest(route_name=route_name):
                response = self.client.get(reverse(f"savings:{route_name}"))
                self.assertEqual(response.status_code, 200)

        popup_urls = [
            reverse("savings:Module_Savings_product_add") + "?popup=1",
            reverse("savings:Module_Savings_account_add") + "?popup=1",
            reverse("savings:Module_Savings_deposit") + "?popup=1",
            reverse("savings:Module_Savings_withdraw") + "?popup=1",
            reverse("savings:Module_Savings_fee") + "?popup=1",
            reverse("savings:Module_Savings_interest") + "?popup=1",
        ]
        for url in popup_urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)

    def test_account_statement_and_pagination_partial_render(self):
        for index in range(26):
            member = Member.unscoped.create(
                branch=self.branch,
                member_code=f"SUI-{index:04d}",
                first_name="Member",
                last_name=str(index),
                status=Member.STATUS_ACTIVE,
            )
            SavingsService(self.request).open_account(
                branch_id=self.branch.pk,
                product_id=self.product.pk,
                member_id=member.pk,
                opened_at=date(2025, 1, 1),
                opening_balance=Decimal("0.00"),
                idempotency_key=uuid.uuid4(),
            )
        account = SavingsAccount.unscoped.order_by("pk").first()
        statement_response = self.client.get(
            reverse("savings:Module_Savings_statement", args=[account.pk])
        )
        list_response = self.client.get(reverse("savings:Module_Savings_accounts"))
        self.assertEqual(statement_response.status_code, 200)
        self.assertEqual(list_response.status_code, 200)
        self.assertContains(list_response, "Page 1 of 2")

    def test_savings_routes_are_denied_without_explicit_permission(self):
        user = get_user_model().objects.create_user(
            username="savings-no-permissions",
            password="A-strong-test-password-127",
            branch=self.branch,
        )
        self.client.force_login(user)
        route_names = [
            "Module_Savings_products",
            "Module_Savings_product_add",
            "Module_Savings_product_edit",
            "Module_Savings_account_add",
            "Module_Savings_accounts",
            "Module_Savings_close_account",
            "Module_Savings_product_edit",
            "Module_Savings_statement",
            "Module_Savings_statement_export",
            "Module_Savings_reactivation_form",
            "Module_Savings_reactivate_account",
            "Module_Savings_balance_report",
            "Module_Savings_reconciliation",
            "Module_Savings_transactions",
            "Module_Savings_deposit",
            "Module_Savings_submit_deposit",
            "Module_Savings_withdraw",
            "Module_Savings_submit_withdraw",
            "Module_Savings_fee",
            "Module_Savings_submit_fee",
            "Module_Savings_interest",
            "Module_Savings_submit_interest",
            "Module_Savings_approve_withdrawal",
            "Module_Savings_rejection_form",
            "Module_Savings_reject_withdrawal",
            "Module_Savings_reversal_form",
            "Module_Savings_reverse",
        ]
        for route_name in route_names:
            args = (
                [999999]
                if route_name
                in {
                    "Module_Savings_close_account",
                    "Module_Savings_product_edit",
                    "Module_Savings_statement",
                    "Module_Savings_statement_export",
                    "Module_Savings_reactivation_form",
                    "Module_Savings_reactivate_account",
                    "Module_Savings_approve_withdrawal",
                    "Module_Savings_rejection_form",
                    "Module_Savings_reject_withdrawal",
                    "Module_Savings_reversal_form",
                    "Module_Savings_reverse",
                }
                else []
            )
            with self.subTest(route_name=route_name):
                response = self.client.get(reverse(f"savings:{route_name}", args=args))
                self.assertEqual(response.status_code, 403)

    def test_state_changing_savings_action_routes_reject_get(self):
        action_names = [
            ("Module_Savings_submit_deposit", []),
            ("Module_Savings_submit_withdraw", []),
            ("Module_Savings_submit_fee", []),
            ("Module_Savings_submit_interest", []),
            ("Module_Savings_close_account", [1]),
            ("Module_Savings_approve_withdrawal", [1]),
            ("Module_Savings_reject_withdrawal", [1]),
            ("Module_Savings_reverse", [1]),
            ("Module_Savings_reactivate_account", [1]),
        ]
        for route_name, args in action_names:
            with self.subTest(route_name=route_name):
                self.assertEqual(
                    self.client.get(
                        reverse(f"savings:{route_name}", args=args)
                    ).status_code,
                    405,
                )


class SavingsBranchIsolationTests(TestCase):
    def setUp(self):
        self.branch_a = Branch.unscoped.create(name="Branch A Savings", code="BSA")
        self.branch_b = Branch.unscoped.create(name="Branch B Savings", code="BSB")
        self.user_a = get_user_model().objects.create_user(
            username="savings-branch-a",
            password="A-strong-test-password-128",
            branch=self.branch_a,
        )
        role = Role.objects.create(name="Savings branch test role")
        route_names = [
            "Module_Savings_accounts",
            "Module_Savings_statement",
            "Module_Savings_statement_export",
            "Module_Savings_submit_deposit",
            "Module_Savings_account_add",
        ]
        permissions = []
        for route_name in route_names:
            permission = Permission.objects.create(
                route_name=route_name,
                url_pattern=f"/test/{route_name}/",
                module="savings",
                action="view",
            )
            permissions.append(permission)
        RolePermission.objects.bulk_create(
            [
                RolePermission(role=role, permission=permission)
                for permission in permissions
            ]
        )
        UserRole.objects.create(user=self.user_a, role=role)
        product = SavingsProduct.objects.create(
            code="ISO",
            name="Isolation savings product",
            savings_type=SavingsProduct.TYPE_GENERAL,
            minimum_opening_balance=Decimal("0.00"),
        )
        self.member_a = Member.unscoped.create(
            branch=self.branch_a,
            member_code="BSA-001",
            first_name="A",
            last_name="Member",
            status=Member.STATUS_ACTIVE,
        )
        self.member_b = Member.unscoped.create(
            branch=self.branch_b,
            member_code="BSB-001",
            first_name="B",
            last_name="Member",
            status=Member.STATUS_ACTIVE,
        )
        self.request_a = RequestFactory().post("/savings/")
        self.request_a.user = self.user_a
        self.request_a.active_branch_id = None
        self.account_a = SavingsService(self.request_a).open_account(
            branch_id=self.branch_a.pk,
            product_id=product.pk,
            member_id=self.member_a.pk,
            opened_at=date(2025, 1, 1),
            opening_balance=Decimal("0.00"),
            idempotency_key=uuid.uuid4(),
        )
        admin = get_user_model().objects.create_superuser(
            username="savings-isolation-admin",
            password="A-strong-test-password-129",
            branch=self.branch_b,
        )
        request_b = RequestFactory().post("/savings/")
        request_b.user = admin
        request_b.active_branch_id = None
        self.account_b = SavingsService(request_b).open_account(
            branch_id=self.branch_b.pk,
            product_id=product.pk,
            member_id=self.member_b.pk,
            opened_at=date(2025, 1, 1),
            opening_balance=Decimal("0.00"),
            idempotency_key=uuid.uuid4(),
        )
        self.client.force_login(self.user_a)

    def test_branch_a_cannot_list_open_post_or_download_branch_b_account(self):
        listing = self.client.get(reverse("savings:Module_Savings_accounts"))
        self.assertContains(listing, self.account_a.account_number)
        self.assertNotContains(listing, self.account_b.account_number)
        self.assertEqual(
            self.client.get(
                reverse("savings:Module_Savings_statement", args=[self.account_b.pk])
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(
                reverse(
                    "savings:Module_Savings_statement_export", args=[self.account_b.pk]
                )
            ).status_code,
            404,
        )
        with self.assertRaises(ValidationError):
            SavingsService(self.request_a).open_account(
                branch_id=self.branch_b.pk,
                product_id=self.account_b.product_id,
                member_id=self.member_b.pk,
                opened_at=date(2025, 1, 1),
                opening_balance=Decimal("0.00"),
                idempotency_key=uuid.uuid4(),
            )
        account_count = SavingsAccount.unscoped.count()
        add_response = self.client.post(
            reverse("savings:Module_Savings_account_add"),
            {
                "branch": self.branch_b.pk,
                "product": self.account_b.product_id,
                "owner_type": "member",
                "member": self.member_b.pk,
                "opened_at": "2025-01-02",
                "opening_balance": "0.00",
                "idempotency_key": str(uuid.uuid4()),
            },
        )
        self.assertEqual(add_response.status_code, 400)
        self.assertEqual(SavingsAccount.unscoped.count(), account_count)
        transaction_count = SavingsTransaction.unscoped.filter(
            account=self.account_b
        ).count()
        response = self.client.post(
            reverse("savings:Module_Savings_submit_deposit"),
            {
                "account": self.account_b.pk,
                "amount": "5.00",
                "transaction_date": "2025-01-02",
                "payment_channel": SavingsTransaction.CHANNEL_CASH,
                "idempotency_key": str(uuid.uuid4()),
                "narration": "",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            SavingsTransaction.unscoped.filter(account=self.account_b).count(),
            transaction_count,
        )


class SavingsConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.assertEqual(connection.vendor, "postgresql")
        SavingsServiceTests.setUp(self)

    def test_two_simultaneous_withdrawals_cannot_overdraw_account(self):
        account = self.open_account(opening_balance=Decimal("100.00"))
        barrier = Barrier(2)

        def withdraw_once():
            close_old_connections()
            try:
                user = get_user_model().objects.get(pk=self.user.pk)
                request = RequestFactory().post("/savings/transactions/withdraw/")
                request.user = user
                request.active_branch_id = None
                barrier.wait(timeout=10)
                try:
                    result = SavingsService(request).withdraw(
                        account_id=account.pk,
                        amount=Decimal("80.00"),
                        transaction_date=date(2025, 1, 2),
                        payment_channel=SavingsTransaction.CHANNEL_CASH,
                        idempotency_key=uuid.uuid4(),
                    )
                except ValidationError:
                    return "rejected"
                return result.status
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(lambda _: withdraw_once(), range(2)))
        account.refresh_from_db()
        self.assertEqual(outcomes.count(SavingsTransaction.STATUS_PENDING), 1)
        self.assertEqual(outcomes.count("rejected"), 1)
        self.assertEqual(account.balance, Decimal("100.00"))
        self.assertEqual(account.reserved_balance, Decimal("80.00"))
