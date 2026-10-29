import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from pathlib import Path
from threading import Barrier

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import DatabaseError, close_old_connections, connection, transaction
from django.test import RequestFactory, TestCase, TransactionTestCase
from django.urls import reverse

from core.accounting.models import (
    Account,
    AccountingPeriod,
    FiscalYear,
    JournalEntry,
    SystemAccountMapping,
)
from core.accounts.models import Permission, Role, RolePermission, UserRole
from core.accounts.permission_utils import get_all_urls, sync_permissions
from core.audit.models import AuditLog
from core.branch.models import Branch, Member, MemberKYC
from core.common.context import current_branch_id_var, current_user_var

from .models import (
    Loan,
    LoanApplication,
    LoanHoliday,
    LoanInstallment,
    LoanPayment,
    LoanProduct,
)
from .services import LoanService, generate_schedule


class LoanScheduleTests(TestCase):
    def test_flat_golden_schedule_rounds_last_installment_and_balances(self):
        schedule = generate_schedule(
            Decimal(50000),
            Decimal("0.24"),
            12,
            LoanProduct.FREQUENCY_MONTHLY,
            LoanProduct.METHOD_FLAT,
            date(2025, 2, 1),
            holiday_convention=LoanProduct.HOLIDAY_KEEP,
        )

        self.assertEqual(schedule["installment"], Decimal("5166.67"))
        self.assertEqual(schedule["interest"], Decimal("12000.00"))
        self.assertEqual(schedule["total_repayable"], Decimal("62000.00"))
        self.assertEqual(schedule["installments"][-1]["total_due"], Decimal("5166.63"))
        self.assertEqual(
            sum(row["principal_due"] + row["interest_due"] for row in schedule["installments"]),
            schedule["total_repayable"],
        )

    def test_declining_golden_schedule_has_expected_first_installment_and_totals(self):
        schedule = generate_schedule(
            Decimal(50000),
            Decimal("0.24"),
            12,
            LoanProduct.FREQUENCY_MONTHLY,
            LoanProduct.METHOD_DECLINING,
            date(2025, 2, 1),
            holiday_convention=LoanProduct.HOLIDAY_KEEP,
        )

        first = schedule["installments"][0]
        self.assertEqual(schedule["installment"], Decimal("4727.98"))
        self.assertEqual(first["interest_due"], Decimal("1000.00"))
        self.assertEqual(first["principal_due"], Decimal("3727.98"))
        self.assertEqual(schedule["interest"], Decimal("6735.76"))
        self.assertEqual(schedule["total_repayable"], Decimal("56735.76"))
        self.assertEqual(
            sum(row["principal_due"] + row["interest_due"] for row in schedule["installments"]),
            schedule["total_repayable"],
        )

    def test_zero_interest_schedule_preserves_principal_exactly(self):
        schedule = generate_schedule(
            Decimal(100),
            Decimal(0),
            3,
            LoanProduct.FREQUENCY_MONTHLY,
            LoanProduct.METHOD_DECLINING,
            date(2025, 2, 1),
            holiday_convention=LoanProduct.HOLIDAY_KEEP,
        )

        self.assertEqual(schedule["interest"], Decimal("0.00"))
        self.assertEqual(schedule["principal"], Decimal("100.00"))
        self.assertEqual(schedule["total_repayable"], Decimal("100.00"))

    def test_holiday_adjustment_does_not_drift_later_monthly_dates(self):
        LoanHoliday.objects.create(date=date(2025, 3, 3), name="Observed holiday")

        schedule = generate_schedule(
            Decimal(1200),
            Decimal(0),
            3,
            LoanProduct.FREQUENCY_MONTHLY,
            LoanProduct.METHOD_FLAT,
            date(2025, 2, 1),
        )

        self.assertEqual(
            [row["due_date"] for row in schedule["installments"]],
            [date(2025, 2, 3), date(2025, 3, 4), date(2025, 4, 1)],
        )


class LoanWorkflowTests(TransactionTestCase):
    def setUp(self):
        self.branch = Branch.unscoped.create(name="Loan Branch", code="LON")
        user_model = get_user_model()
        self.maker = user_model.objects.create_user(
            username="loan-maker",
            password="Test-password-12345",
            branch=self.branch,
        )
        self.checker = user_model.objects.create_user(
            username="loan-checker",
            password="Test-password-12345",
            branch=self.branch,
        )
        self.writeoff_checker = user_model.objects.create_user(
            username="loan-writeoff-checker",
            password="Test-password-12345",
            branch=self.branch,
        )
        self.current_user_token = current_user_var.set(self.maker)
        self.current_branch_token = current_branch_id_var.set(None)
        self.addCleanup(current_user_var.reset, self.current_user_token)
        self.addCleanup(current_branch_id_var.reset, self.current_branch_token)
        self.request = RequestFactory().post("/loans/applications/")
        self.request.user = self.maker
        self.request.active_branch_id = None

        year = FiscalYear.objects.create(
            name="Loan FY 2025",
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
        )
        AccountingPeriod.objects.create(
            fiscal_year=year,
            number=1,
            name="FY 2025",
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
        )
        concurrent_year = FiscalYear.objects.create(
            name="Loan FY 2026",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
        )
        AccountingPeriod.objects.create(
            fiscal_year=concurrent_year,
            number=1,
            name="FY 2026",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
        )
        self._create_mappings()
        self.product = LoanProduct.objects.create(
            code="GOLD",
            name="Golden example",
            interest_method=LoanProduct.METHOD_DECLINING,
            annual_interest_rate=Decimal("24.0000"),
            min_amount=Decimal("100.00"),
            max_amount=Decimal("100000.00"),
            min_term=1,
            max_term=24,
            installment_frequency=LoanProduct.FREQUENCY_MONTHLY,
            requires_verified_kyc=True,
        )
        self.member = Member.unscoped.create(
            branch=self.branch,
            member_code="LON-0001",
            first_name="Loan",
            last_name="Member",
            status=Member.STATUS_ACTIVE,
        )
        MemberKYC.objects.create(
            member=self.member,
            document_type=MemberKYC.DOC_TYPE_NATIONAL_ID,
            status=MemberKYC.STATUS_VERIFIED,
            is_verified=True,
            verified_by=self.checker,
        )

    def _create_mappings(self):
        account_types = {
            "cash_in_hand": (Account.ASSET, Account.DEBIT),
            "bank_accounts": (Account.ASSET, Account.DEBIT),
            "loans_to_members": (Account.ASSET, Account.DEBIT),
            "loan_loss_provision": (Account.ASSET, Account.CREDIT),
            "fee_income": (Account.INCOME, Account.CREDIT),
            "interest_income": (Account.INCOME, Account.CREDIT),
            "penalty_income": (Account.INCOME, Account.CREDIT),
            "recovery_income": (Account.INCOME, Account.CREDIT),
        }
        for index, (key, (account_type, normal_balance)) in enumerate(
            account_types.items(), start=1
        ):
            account = Account.objects.create(
                code=f"LA{index:03d}",
                name=key.replace("_", " ").title(),
                account_type=account_type,
                normal_balance=normal_balance,
            )
            SystemAccountMapping.objects.create(key=key, account=account)

    def service_as(self, user):
        current_user_var.set(user)
        self.request.user = user
        return LoanService(self.request)

    def create_submitted_application(self, *, amount=Decimal("12000.00"), term=12):
        service = self.service_as(self.maker)
        application = service.create_application(
            branch_id=self.branch.pk,
            member_id=self.member.pk,
            product_id=self.product.pk,
            amount=amount,
            term=term,
            purpose="Working capital",
            idempotency_key=uuid.uuid4(),
        )
        service.submit(application_id=application.pk)
        return application

    def approve_application(self, application):
        return self.service_as(self.checker).review(
            application_id=application.pk,
            decision=LoanApplication.STATUS_APPROVED,
            comment="Eligibility verified",
            approved_amount=application.requested_amount,
        )

    def disburse(self, application):
        return self.service_as(self.maker).disburse(
            application_id=application.pk,
            disbursement_date=date(2025, 1, 15),
            channel="cash_in_hand",
            idempotency_key=uuid.uuid4(),
        )

    def test_maker_checker_disbursement_posts_once_with_balanced_ledger(self):
        application = self.create_submitted_application()
        with self.assertRaises(ValidationError):
            self.service_as(self.maker).review(
                application_id=application.pk,
                decision=LoanApplication.STATUS_APPROVED,
                comment="Self approval",
            )

        self.approve_application(application)
        loan = self.disburse(application)
        replay = self.service_as(self.maker).disburse(
            application_id=application.pk,
            disbursement_date=date(2025, 1, 15),
            channel="cash_in_hand",
            idempotency_key=loan.idempotency_key,
        )

        self.assertEqual(replay.pk, loan.pk)
        self.assertEqual(loan.journal_entry.status, JournalEntry.STATUS_POSTED)
        self.assertEqual(loan.journal_entry.lines.count(), 2)
        self.assertEqual(
            sum(line.debit for line in loan.journal_entry.lines.all()),
            Decimal("12000.00"),
        )
        self.assertTrue(
            AuditLog.objects.filter(
                entity_name="Loan",
                entity_id=str(loan.pk),
                action="Disburse",
                branch_id=self.branch.pk,
            ).exists()
        )

    def test_application_eligibility_checks_kyc_compulsory_savings_and_cycle_cap(self):
        MemberKYC.objects.filter(member=self.member).delete()
        with self.assertRaises(ValidationError):
            self.service_as(self.maker).create_application(
                branch_id=self.branch.pk,
                member_id=self.member.pk,
                product_id=self.product.pk,
                amount=Decimal("12000.00"),
                term=12,
                purpose="Working capital",
                idempotency_key=uuid.uuid4(),
            )

        MemberKYC.objects.create(
            member=self.member,
            status=MemberKYC.STATUS_VERIFIED,
            is_verified=True,
            verified_by=self.checker,
        )
        self.product.required_savings_rate = Decimal("50.0000")
        self.product.save(update_fields=["required_savings_rate"])
        with self.assertRaises(ValidationError):
            self.service_as(self.maker).create_application(
                branch_id=self.branch.pk,
                member_id=self.member.pk,
                product_id=self.product.pk,
                amount=Decimal("12000.00"),
                term=12,
                purpose="Working capital",
                idempotency_key=uuid.uuid4(),
            )

        self.product.required_savings_rate = Decimal(0)
        self.product.max_concurrent_loans = 2
        self.product.cycle_limits = {"1": "20000", "2": "1000"}
        self.product.save(
            update_fields=[
                "required_savings_rate",
                "max_concurrent_loans",
                "cycle_limits",
            ]
        )
        application = self.create_submitted_application()
        self.approve_application(application)
        self.disburse(application)
        with self.assertRaises(ValidationError):
            self.service_as(self.maker).create_application(
                branch_id=self.branch.pk,
                member_id=self.member.pk,
                product_id=self.product.pk,
                amount=Decimal("12000.00"),
                term=12,
                purpose="Next cycle",
                idempotency_key=uuid.uuid4(),
            )

    def test_approver_limit_allows_a_lower_amount_but_rejects_excess(self):
        self.product.approval_limit = Decimal("5000.00")
        self.product.save(update_fields=["approval_limit"])
        application = self.create_submitted_application()
        service = self.service_as(self.checker)

        with self.assertRaises(ValidationError):
            service.review(
                application_id=application.pk,
                decision=LoanApplication.STATUS_APPROVED,
                comment="Above authority",
                approved_amount=Decimal("12000.00"),
            )
        approved = service.review(
            application_id=application.pk,
            decision=LoanApplication.STATUS_APPROVED,
            comment="Reduced to delegated limit",
            approved_amount=Decimal("5000.00"),
        )

        self.assertEqual(approved.approved_amount, Decimal("5000.00"))

    def test_repayment_is_locked_atomic_idempotent_and_posts(self):
        application = self.create_submitted_application()
        self.approve_application(application)
        loan = self.disburse(application)
        installment = LoanInstallment.objects.get(
            loan=loan, schedule_version=loan.schedule_version, number=1
        )
        key = uuid.uuid4()

        payment = self.service_as(self.checker).repay(
            loan_id=loan.pk,
            amount=installment.total_due,
            payment_date=installment.due_date,
            idempotency_key=key,
            payment_channel=LoanPayment.CHANNEL_BANK,
        )
        replay = self.service_as(self.checker).repay(
            loan_id=loan.pk,
            amount=installment.total_due,
            payment_date=installment.due_date,
            idempotency_key=key,
            payment_channel=LoanPayment.CHANNEL_BANK,
        )
        loan.refresh_from_db()

        self.assertEqual(payment.pk, replay.pk)
        self.assertEqual(payment.journal_entry.status, JournalEntry.STATUS_POSTED)
        self.assertEqual(payment.payment_channel, LoanPayment.CHANNEL_BANK)
        self.assertEqual(loan.outstanding_principal, loan.principal - payment.principal_paid)
        with self.assertRaises(ValidationError):
            self.service_as(self.checker).repay(
                loan_id=loan.pk,
                amount=installment.total_due + Decimal("1.00"),
                payment_date=installment.due_date,
                idempotency_key=key,
                payment_channel=LoanPayment.CHANNEL_BANK,
            )
        with self.assertRaises(TypeError):
            payment.delete()
        with self.assertRaises(TypeError):
            LoanPayment.objects.filter(pk=payment.pk).update(amount=Decimal("1.00"))

    def test_disbursement_fees_are_deducted_and_credited_separately(self):
        self.product.processing_fee = Decimal("100.00")
        self.product.insurance_fee = Decimal("50.00")
        self.product.save(update_fields=["processing_fee", "insurance_fee"])
        application = self.create_submitted_application()
        self.approve_application(application)

        loan = self.disburse(application)
        lines = list(loan.journal_entry.lines.all())

        self.assertEqual(sum(line.debit for line in lines), Decimal("12000.00"))
        self.assertEqual(sum(line.credit for line in lines), Decimal("12000.00"))
        self.assertEqual(len(lines), 3)
        self.assertEqual(
            sum(line.credit for line in lines if line.account.code == "LA005"),
            Decimal("150.00"),
        )

    def test_late_penalty_is_assessed_capped_and_allocated_before_interest(self):
        self.product.late_penalty_rate = Decimal("1.0000")
        self.product.penalty_cap_rate = Decimal("25.0000")
        self.product.save(update_fields=["late_penalty_rate", "penalty_cap_rate"])
        application = self.create_submitted_application()
        self.approve_application(application)
        loan = self.disburse(application)
        installment = LoanInstallment.objects.get(
            loan=loan, schedule_version=loan.schedule_version, number=1
        )

        payment = self.service_as(self.checker).repay(
            loan_id=loan.pk,
            amount=Decimal("5.00"),
            payment_date=installment.due_date.replace(day=installment.due_date.day + 1),
            idempotency_key=uuid.uuid4(),
        )
        installment.refresh_from_db()

        self.assertGreater(payment.penalty_paid, Decimal(0))
        self.assertEqual(payment.penalty_paid, Decimal("5.00"))
        self.assertEqual(installment.interest_paid, Decimal("0.00"))
        self.assertEqual(payment.journal_entry.status, JournalEntry.STATUS_POSTED)

    def test_early_settlement_waives_unearned_interest_and_posts_fee(self):
        self.product.early_settlement_fee = Decimal("25.00")
        self.product.save(update_fields=["early_settlement_fee"])
        application = self.create_submitted_application()
        self.approve_application(application)
        loan = self.disburse(application)

        payment = self.service_as(self.checker).settle(
            loan_id=loan.pk,
            settlement_date=date(2025, 1, 20),
            idempotency_key=uuid.uuid4(),
        )
        loan.refresh_from_db()

        self.assertEqual(payment.amount, Decimal("12025.00"))
        self.assertEqual(payment.fee_paid, Decimal("25.00"))
        self.assertEqual(loan.status, Loan.STATUS_CLOSED)
        self.assertEqual(payment.journal_entry.status, JournalEntry.STATUS_POSTED)

    def test_par_uses_days_past_due_and_unpaid_interest_or_principal(self):
        application = self.create_submitted_application()
        self.approve_application(application)
        loan = self.disburse(application)
        first_due = LoanInstallment.objects.get(
            loan=loan, schedule_version=loan.schedule_version, number=1
        ).due_date

        portfolio = self.service_as(self.checker).portfolio(
            as_of_date=date(2025, 5, 1), branch_ids={self.branch.pk}
        )

        self.assertEqual(portfolio["par"][1]["amount"], loan.principal)
        self.assertEqual(portfolio["par"][30]["amount"], loan.principal)
        self.assertEqual(portfolio["par"][90]["amount"], Decimal("0.00"))
        self.assertLess(first_due, date(2025, 5, 1))

    def test_runtime_role_cannot_update_or_delete_posted_loan_payments(self):
        application = self.create_submitted_application()
        self.approve_application(application)
        loan = self.disburse(application)
        installment = LoanInstallment.objects.get(
            loan=loan, schedule_version=loan.schedule_version, number=1
        )
        payment = self.service_as(self.checker).repay(
            loan_id=loan.pk,
            amount=installment.total_due,
            payment_date=installment.due_date,
            idempotency_key=uuid.uuid4(),
        )
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
                    "SELECT has_table_privilege("
                    "'erp_runtime', 'loan_payments', 'UPDATE'), "
                    "has_table_privilege("
                    "'erp_runtime', 'loan_payments', 'DELETE')"
                )
                self.assertEqual(cursor.fetchone(), (False, False))
                for sql in (
                    "UPDATE loan_payments SET amount = 1 WHERE id = %s",
                    "DELETE FROM loan_payments WHERE id = %s",
                ):
                    with (
                        self.subTest(sql=sql),
                        self.assertRaises(DatabaseError),
                        transaction.atomic(),
                    ):
                        cursor.execute(sql, [payment.pk])
            finally:
                cursor.execute("RESET ROLE")

    def test_concurrent_retries_of_full_repayment_create_one_payment(self):
        application = self.create_submitted_application()
        self.approve_application(application)
        loan = self.disburse(application)
        installments = list(
            LoanInstallment.objects.filter(
                loan=loan, schedule_version=loan.schedule_version
            )
        )
        amount = sum((row.total_due for row in installments), Decimal("0.00"))
        payment_date = installments[-1].due_date
        key = uuid.uuid4()
        barrier = Barrier(2)

        def submit_payment():
            close_old_connections()
            user = get_user_model().objects.get(pk=self.checker.pk)
            current_user_var.set(user)
            current_branch_id_var.set(None)
            request = RequestFactory().post("/loans/repayments/")
            request.user = user
            request.active_branch_id = None
            try:
                barrier.wait(timeout=10)
                return LoanService(request).repay(
                    loan_id=loan.pk,
                    amount=amount,
                    payment_date=payment_date,
                    idempotency_key=key,
                ).pk
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: submit_payment(), range(2)))

        loan.refresh_from_db()
        self.assertEqual(results[0], results[1])
        self.assertEqual(LoanPayment.objects.filter(loan=loan, idempotency_key=key).count(), 1)
        self.assertEqual(loan.status, Loan.STATUS_CLOSED)
        self.assertEqual(loan.outstanding_principal, Decimal("0.00"))

    def test_missing_mapping_rolls_back_disbursement_and_draft_journal(self):
        application = self.create_submitted_application()
        self.approve_application(application)
        SystemAccountMapping.objects.filter(key="cash_in_hand").delete()
        journals_before = JournalEntry.objects.count()

        with self.assertRaises(ValidationError):
            self.disburse(application)

        self.assertFalse(Loan.objects.filter(application=application).exists())
        self.assertEqual(JournalEntry.objects.count(), journals_before)
        application.refresh_from_db()
        self.assertEqual(application.status, LoanApplication.STATUS_APPROVED)

    def test_reschedule_preserves_old_version_and_is_idempotent(self):
        application = self.create_submitted_application()
        self.approve_application(application)
        loan = self.disburse(application)
        old_count = LoanInstallment.objects.filter(loan=loan, schedule_version=1).count()
        key = uuid.uuid4()

        service = self.service_as(self.checker)
        first = service.reschedule(
            loan_id=loan.pk,
            new_term=10,
            effective_date=date(2025, 1, 20),
            reason="Seasonal cash flow",
            idempotency_key=key,
        )
        replay = service.reschedule(
            loan_id=loan.pk,
            new_term=10,
            effective_date=date(2025, 1, 20),
            reason="Seasonal cash flow",
            idempotency_key=key,
        )

        self.assertEqual(first.pk, replay.pk)
        self.assertEqual(first.schedule_version, 2)
        self.assertEqual(
            LoanInstallment.objects.filter(loan=loan, schedule_version=1).count(),
            old_count,
        )
        self.assertEqual(
            LoanInstallment.objects.filter(loan=loan, schedule_version=2).count(),
            10,
        )

    def test_writeoff_and_recovery_are_idempotent_ledger_postings(self):
        application = self.create_submitted_application()
        self.approve_application(application)
        loan = self.disburse(application)
        writeoff_key = uuid.uuid4()
        service = self.service_as(self.writeoff_checker)
        written_off = service.write_off(
            loan_id=loan.pk,
            write_off_date=date(2025, 1, 20),
            reason="Unrecoverable account",
            idempotency_key=writeoff_key,
        )
        repeated = service.write_off(
            loan_id=loan.pk,
            write_off_date=date(2025, 1, 20),
            reason="Unrecoverable account",
            idempotency_key=writeoff_key,
        )
        recovery_key = uuid.uuid4()
        recovery = service.recover(
            loan_id=loan.pk,
            amount=Decimal("100.00"),
            payment_date=date(2025, 2, 1),
            payment_channel=LoanPayment.CHANNEL_CASH,
            idempotency_key=recovery_key,
        )
        recovery_replay = service.recover(
            loan_id=loan.pk,
            amount=Decimal("100.00"),
            payment_date=date(2025, 2, 1),
            payment_channel=LoanPayment.CHANNEL_CASH,
            idempotency_key=recovery_key,
        )
        written_off.refresh_from_db()

        self.assertEqual(repeated.pk, loan.pk)
        self.assertEqual(written_off.status, Loan.STATUS_WRITTEN_OFF)
        self.assertEqual(recovery.pk, recovery_replay.pk)
        self.assertEqual(written_off.recovered_amount, Decimal("100.00"))
        self.assertEqual(recovery.journal_entry.status, JournalEntry.STATUS_POSTED)


class LoanRouteTests(TestCase):
    def setUp(self):
        self.branch = Branch.unscoped.create(name="Loan Route Branch", code="LRB")
        self.user = get_user_model().objects.create_user(
            username="loan-route-user",
            password="Test-password-12345",
            branch=self.branch,
        )
        self.client.force_login(self.user)
        sync_permissions()

    def test_every_loan_route_is_registered_for_explicit_permissions(self):
        route_names = {
            route["route_name"]
            for route in get_all_urls()
            if route["route_name"].startswith("Module_Loans_")
        }
        expected = {
            "Module_Loans_products",
            "Module_Loans_product_add",
            "Module_Loans_product_edit",
            "Module_Loans_applications",
            "Module_Loans_application_add",
            "Module_Loans_application_submit",
            "Module_Loans_application_review",
            "Module_Loans_application_cancel",
            "Module_Loans_disbursement_add",
            "Module_Loans_disbursements",
            "Module_Loans_portfolio",
            "Module_Loans_repayments",
            "Module_Loans_repayment_add",
            "Module_Loans_schedule",
            "Module_Loans_reschedule",
            "Module_Loans_settle",
            "Module_Loans_write_off",
            "Module_Loans_recovery",
        }
        self.assertEqual(route_names, expected)

    def test_every_loan_route_is_denied_without_its_permission(self):
        for route in get_all_urls():
            route_name = route["route_name"]
            if not route_name.startswith("Module_Loans_"):
                continue
            args = [999999] if "<int:pk>" in route["url"] else []
            with self.subTest(route_name=route_name):
                response = self.client.get(
                    reverse(f"loans:{route_name}", args=args)
                )
                self.assertEqual(response.status_code, 403)

    def test_get_is_not_allowed_on_state_transition_routes(self):
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        for route_name in (
            "Module_Loans_application_submit",
            "Module_Loans_application_cancel",
        ):
            with self.subTest(route_name=route_name):
                response = self.client.get(
                    reverse(f"loans:{route_name}", args=[1])
                )
                self.assertEqual(response.status_code, 405)

    def test_application_list_respects_branch_scope(self):
        other_branch = Branch.unscoped.create(
            name="Other Loan Route Branch", code="OLR"
        )
        product = LoanProduct.objects.create(
            code="ROUTE",
            name="Route test",
            interest_method=LoanProduct.METHOD_FLAT,
            annual_interest_rate=Decimal(0),
            min_amount=Decimal(1),
            max_amount=Decimal(100),
            min_term=1,
            max_term=2,
            installment_frequency=LoanProduct.FREQUENCY_MONTHLY,
            requires_verified_kyc=False,
        )
        member = Member.unscoped.create(
            branch=other_branch,
            member_code="OTHER-LON",
            first_name="Other",
            last_name="Member",
            status=Member.STATUS_ACTIVE,
        )
        LoanApplication.unscoped.create(
            branch=other_branch,
            member=member,
            product=product,
            requested_amount=Decimal(10),
            term=1,
            purpose="Branch isolation",
            created_by=self.user,
            idempotency_key=uuid.uuid4(),
        )
        role = Role.objects.create(name="loan-application-reader")
        permission = Permission.objects.get(
            route_name="Module_Loans_applications"
        )
        RolePermission.objects.create(role=role, permission=permission)
        UserRole.objects.create(user=self.user, role=role)

        response = self.client.get(reverse("loans:Module_Loans_applications"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "OTHER-LON")
