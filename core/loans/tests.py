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
from core.savings.models import SavingsProduct, SavingsTransaction
from core.savings.services import SavingsService

from .models import (
    Loan,
    LoanApplication,
    LoanApprovalTier,
    LoanCollateral,
    LoanGuarantor,
    LoanHoliday,
    LoanInstallment,
    LoanPARBucket,
    LoanPayment,
    LoanProduct,
    LoanStatusHistory,
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
        for name, minimum, maximum, provision_rate in (
            ("Regular", 0, 0, "1.0000"),
            ("Watchlist", 1, 29, "5.0000"),
            ("Substandard", 30, 59, "25.0000"),
            ("Doubtful", 60, 89, "50.0000"),
            ("Bad / Loss", 90, None, "100.0000"),
        ):
            LoanPARBucket.objects.get_or_create(
                name=name,
                defaults={
                    "minimum_days": minimum,
                    "maximum_days": maximum,
                    "provision_rate": Decimal(provision_rate),
                    "is_active": True,
                },
            )
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
            "insurance_income": (Account.INCOME, Account.CREDIT),
            "loan_overpayment_payable": (Account.LIABILITY, Account.CREDIT),
            "interest_income": (Account.INCOME, Account.CREDIT),
            "penalty_income": (Account.INCOME, Account.CREDIT),
            "recovery_income": (Account.INCOME, Account.CREDIT),
            "member_savings": (Account.LIABILITY, Account.CREDIT),
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

    def grant_waiver_permission(self, user):
        permission, _ = Permission.objects.get_or_create(
            route_name="Module_Loans_waive_interest",
            defaults={
                "url_pattern": "/loans/<int:pk>/waive-interest/",
                "module": "Loans",
                "action": "waive_interest",
            },
        )
        waiver_role = Role.objects.create(name=f"loan-waiver-{user.pk}")
        RolePermission.objects.create(role=waiver_role, permission=permission)
        UserRole.objects.create(user=user, role=waiver_role)

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
        self.assertTrue(
            LoanStatusHistory.objects.filter(
                loan=loan,
                old_status="",
                new_status=Loan.STATUS_ACTIVE,
            ).exists()
        )

    def test_disbursed_loan_keeps_the_product_terms_copied_at_creation(self):
        application = self.create_submitted_application()
        self.approve_application(application)
        loan = self.disburse(application)

        self.product.annual_interest_rate = Decimal("36.0000")
        self.product.penalty_grace_days = 7
        self.product.save(update_fields=["annual_interest_rate", "penalty_grace_days"])
        loan = Loan.objects.select_related("product").get(pk=loan.pk)

        self.assertEqual(loan.product.annual_interest_rate, Decimal("36.0000"))
        self.assertEqual(
            loan.product_term("annual_interest_rate"), Decimal("24.0000")
        )
        self.assertEqual(loan.product_term("penalty_grace_days"), 0)

    def test_guarantor_and_collateral_requirements_are_validated_and_audited(self):
        self.product.requires_guarantor = True
        self.product.requires_collateral = True
        self.product.save(update_fields=["requires_guarantor", "requires_collateral"])
        service = self.service_as(self.maker)
        application_args = {
            "branch_id": self.branch.pk,
            "member_id": self.member.pk,
            "product_id": self.product.pk,
            "amount": Decimal("12000.00"),
            "term": 12,
            "purpose": "Working capital",
        }

        with self.assertRaises(ValidationError):
            service.create_application(
                **application_args,
                idempotency_key=uuid.uuid4(),
            )

        guarantor = Member.unscoped.create(
            branch=self.branch,
            member_code="LON-0002",
            first_name="Loan",
            last_name="Guarantor",
            status=Member.STATUS_ACTIVE,
        )
        application = service.create_application(
            **application_args,
            idempotency_key=uuid.uuid4(),
            guarantor_id=guarantor.pk,
            collateral={
                "description": "Equipment",
                "reference_number": "EQ-12",
                "estimated_value": Decimal("15000.00"),
            },
        )

        self.assertEqual(
            LoanGuarantor.objects.get(application=application).member_id,
            guarantor.pk,
        )
        self.assertEqual(
            LoanCollateral.objects.get(application=application).estimated_value,
            Decimal("15000.00"),
        )
        self.assertTrue(
            AuditLog.objects.filter(
                entity_name="LoanApplication",
                entity_id=str(application.pk),
                action="AddGuarantor",
            ).exists()
        )
        self.assertTrue(
            AuditLog.objects.filter(
                entity_name="LoanApplication",
                entity_id=str(application.pk),
                action="AddCollateral",
            ).exists()
        )

    def test_approval_tier_limits_are_applied_by_role_and_branch_level(self):
        role = Role.objects.create(name="loan-branch-approver")
        UserRole.objects.create(user=self.checker, role=role)
        LoanApprovalTier.objects.create(
            branch_type=self.branch.branch_type,
            branch=self.branch,
            role=role,
            amount_limit=Decimal("5000.00"),
        )
        self.product.approval_limit = None
        self.product.save(update_fields=["approval_limit"])
        application = self.create_submitted_application()
        service = self.service_as(self.checker)

        with self.assertRaises(ValidationError):
            service.review(
                application_id=application.pk,
                decision=LoanApplication.STATUS_APPROVED,
                comment="Above branch authority",
                approved_amount=Decimal("12000.00"),
            )

        approved = service.review(
            application_id=application.pk,
            decision=LoanApplication.STATUS_APPROVED,
            comment="Within branch authority",
            approved_amount=Decimal("5000.00"),
        )

        self.assertEqual(approved.approved_amount, Decimal("5000.00"))

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
        payment_lines = payment.journal_entry.lines.all()
        self.assertEqual(
            sum(line.debit for line in payment_lines),
            sum(line.credit for line in payment_lines),
        )
        self.assertEqual(
            sum(line.debit for line in payment_lines),
            payment.amount,
        )
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
        self.assertEqual(len(lines), 4)
        self.assertEqual(
            sum(line.credit for line in lines if line.account.code == "LA005"),
            Decimal("100.00"),
        )
        self.assertEqual(
            sum(line.credit for line in lines if line.account.code == "LA006"),
            Decimal("50.00"),
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
        self.grant_waiver_permission(self.checker)

        payment = self.service_as(self.checker).settle(
            loan_id=loan.pk,
            settlement_date=date(2025, 1, 20),
            idempotency_key=uuid.uuid4(),
            reason="Early settlement approved under policy.",
        )
        loan.refresh_from_db()

        self.assertEqual(payment.amount, Decimal("12025.00"))
        self.assertEqual(payment.fee_paid, Decimal("25.00"))
        self.assertEqual(loan.status, Loan.STATUS_CLOSED)
        self.assertEqual(payment.journal_entry.status, JournalEntry.STATUS_POSTED)
        waiver_audit = AuditLog.objects.get(
            entity_name="Loan",
            entity_id=str(loan.pk),
            action="WaiveLoanInterest",
        )
        self.assertIn("waived_interest", waiver_audit.new_values)
        self.assertEqual(
            waiver_audit.remarks,
            "Early settlement approved under policy.",
        )

    def test_full_and_pro_rata_settlement_policies_are_distinct(self):
        self.product.early_settlement_policy = LoanProduct.SETTLEMENT_FULL
        self.product.save(update_fields=["early_settlement_policy"])
        full_application = self.create_submitted_application()
        self.approve_application(full_application)
        full_loan = self.disburse(full_application)
        full_interest = sum(
            (
                row.interest_remaining
                for row in LoanInstallment.objects.filter(loan=full_loan)
            ),
            Decimal("0.00"),
        )
        full_payment = self.service_as(self.checker).settle(
            loan_id=full_loan.pk,
            settlement_date=date(2025, 1, 20),
            idempotency_key=uuid.uuid4(),
            reason="Full scheduled interest policy.",
        )
        self.assertEqual(full_payment.amount, full_loan.principal + full_interest)

        self.product.early_settlement_policy = LoanProduct.SETTLEMENT_PRO_RATA
        self.product.save(update_fields=["early_settlement_policy"])
        second_member = Member.unscoped.create(
            branch=self.branch,
            member_code="LON-0002",
            first_name="Pro-rata",
            last_name="Member",
            status=Member.STATUS_ACTIVE,
        )
        MemberKYC.objects.create(
            member=second_member,
            document_type=MemberKYC.DOC_TYPE_NATIONAL_ID,
            status=MemberKYC.STATUS_VERIFIED,
            is_verified=True,
            verified_by=self.checker,
        )
        second_application = self.service_as(self.maker).create_application(
            branch_id=self.branch.pk,
            member_id=second_member.pk,
            product_id=self.product.pk,
            amount=Decimal("12000.00"),
            term=12,
            purpose="Pro-rata settlement",
            idempotency_key=uuid.uuid4(),
        )
        self.service_as(self.maker).submit(application_id=second_application.pk)
        self.approve_application(second_application)
        pro_rata_loan = self.disburse(second_application)
        self.grant_waiver_permission(self.checker)
        scheduled_interest = sum(
            (
                row.interest_remaining
                for row in LoanInstallment.objects.filter(loan=pro_rata_loan)
            ),
            Decimal("0.00"),
        )
        pro_rata_payment = self.service_as(self.checker).settle(
            loan_id=pro_rata_loan.pk,
            settlement_date=date(2025, 2, 15),
            idempotency_key=uuid.uuid4(),
            reason="Pro-rata policy waiver.",
        )

        self.assertGreater(pro_rata_payment.amount, pro_rata_loan.principal)
        self.assertLess(
            pro_rata_payment.amount,
            pro_rata_loan.principal + scheduled_interest,
        )

    def test_early_settlement_waiver_requires_permission_and_reason(self):
        application = self.create_submitted_application()
        self.approve_application(application)
        loan = self.disburse(application)

        with self.assertRaises(ValidationError) as raised:
            self.service_as(self.checker).settle(
                loan_id=loan.pk,
                settlement_date=date(2025, 1, 20),
                idempotency_key=uuid.uuid4(),
                reason="Waiver requested.",
            )

        self.assertIn("permission", raised.exception.message_dict)
        loan.refresh_from_db()
        self.assertEqual(loan.status, Loan.STATUS_ACTIVE)

    def test_overpayment_refund_is_atomic_idempotent_and_ledger_posted(self):
        application = self.create_submitted_application()
        self.approve_application(application)
        loan = self.disburse(application)
        installments = list(
            LoanInstallment.objects.filter(
                loan=loan, schedule_version=loan.schedule_version
            )
        )
        scheduled_total = sum(
            (row.total_due for row in installments), Decimal("0.00")
        )
        key = uuid.uuid4()
        service = self.service_as(self.checker)
        payment = service.repay(
            loan_id=loan.pk,
            amount=scheduled_total + Decimal("100.00"),
            payment_date=installments[-1].due_date,
            idempotency_key=key,
        )
        replay = service.repay(
            loan_id=loan.pk,
            amount=scheduled_total + Decimal("100.00"),
            payment_date=installments[-1].due_date,
            idempotency_key=key,
        )

        self.assertEqual(payment.pk, replay.pk)
        self.assertEqual(payment.overpayment_amount, Decimal("100.00"))
        self.assertEqual(payment.refund_journal_entry.status, JournalEntry.STATUS_POSTED)
        for journal in (payment.journal_entry, payment.refund_journal_entry):
            lines = list(journal.lines.all())
            self.assertEqual(
                sum(line.debit for line in lines),
                sum(line.credit for line in lines),
            )

    def test_overpayment_savings_transfer_posts_once_to_member_account(self):
        self.product.overpayment_policy = LoanProduct.OVERPAYMENT_SAVINGS
        self.product.save(update_fields=["overpayment_policy"])
        savings_product = SavingsProduct.objects.create(
            code="LOAN-TRANSFER",
            name="Loan overpayment destination",
            savings_type=SavingsProduct.TYPE_GENERAL,
        )
        savings_account = SavingsService(self.request).open_account(
            branch_id=self.branch.pk,
            product_id=savings_product.pk,
            member_id=self.member.pk,
            opened_at=date(2025, 1, 1),
            opening_balance=Decimal("0.00"),
            idempotency_key=uuid.uuid4(),
        )
        application = self.create_submitted_application()
        self.approve_application(application)
        loan = self.disburse(application)
        installments = list(
            LoanInstallment.objects.filter(
                loan=loan, schedule_version=loan.schedule_version
            )
        )
        scheduled_total = sum(
            (row.total_due for row in installments), Decimal("0.00")
        )
        key = uuid.uuid4()
        service = self.service_as(self.checker)
        payment = service.repay(
            loan_id=loan.pk,
            amount=scheduled_total + Decimal("100.00"),
            payment_date=installments[-1].due_date,
            idempotency_key=key,
        )
        replay = service.repay(
            loan_id=loan.pk,
            amount=scheduled_total + Decimal("100.00"),
            payment_date=installments[-1].due_date,
            idempotency_key=key,
        )

        savings_account.refresh_from_db()
        self.assertEqual(payment.pk, replay.pk)
        self.assertEqual(payment.overpayment_amount, Decimal("100.00"))
        self.assertEqual(payment.savings_transaction.amount, Decimal("100.00"))
        self.assertEqual(
            SavingsTransaction.objects.filter(
                account=savings_account,
                idempotency_key=uuid.uuid5(key, f"loan-overpayment-{loan.pk}"),
            ).count(),
            1,
        )
        self.assertEqual(savings_account.balance, Decimal("100.00"))
        self.assertEqual(
            payment.savings_transaction.journal_entry.status,
            JournalEntry.STATUS_POSTED,
        )

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

    def test_classification_report_uses_configured_par_buckets(self):
        application = self.create_submitted_application()
        self.approve_application(application)
        loan = self.disburse(application)

        report = self.service_as(self.checker).classification_report(
            as_of_date=date(2025, 2, 1),
            branch_ids={self.branch.pk},
        )
        regular = LoanPARBucket.objects.get(name="Regular")

        self.assertEqual(report["principal"], loan.principal)
        self.assertEqual(report["loan_count"], 1)
        self.assertEqual(report["buckets"][0]["name"], regular.name)
        self.assertEqual(report["buckets"][0]["principal"], loan.principal)

    def test_statement_history_and_classification_exports_render(self):
        self.product.late_penalty_rate = Decimal("1.0000")
        self.product.penalty_cap_rate = Decimal("25.0000")
        self.product.save(update_fields=["late_penalty_rate", "penalty_cap_rate"])
        application = self.create_submitted_application()
        self.approve_application(application)
        loan = self.disburse(application)
        service = self.service_as(self.checker)
        service.reschedule(
            loan_id=loan.pk,
            new_term=10,
            effective_date=date(2025, 1, 20),
            reason="Statement history fixture.",
            idempotency_key=uuid.uuid4(),
        )
        loan.refresh_from_db()
        first_installment = LoanInstallment.objects.get(
            loan=loan,
            schedule_version=loan.schedule_version,
            number=1,
        )
        service.repay(
            loan_id=loan.pk,
            amount=Decimal("5.00"),
            payment_date=first_installment.due_date.replace(
                day=first_installment.due_date.day + 1
            ),
            idempotency_key=uuid.uuid4(),
        )
        self.checker.is_superuser = True
        self.checker.save(update_fields=["is_superuser"])
        self.client.force_login(self.checker)

        statement = self.client.get(
            reverse("loans:Module_Loans_statement", args=[loan.pk])
        )
        history = self.client.get(
            reverse("loans:Module_Loans_history", args=[loan.pk])
        )
        excel = self.client.get(reverse("loans:Module_Loans_classification_excel"))
        pdf = self.client.get(reverse("loans:Module_Loans_classification_pdf"))

        self.assertEqual(statement.status_code, 200)
        self.assertContains(statement, "Repayment schedule versions")
        self.assertContains(statement, "Version 1")
        self.assertContains(statement, "Version 2")
        self.assertContains(statement, "Payments")
        self.assertContains(statement, "Penalties")
        self.assertContains(statement, "Status history")
        self.assertEqual(history.status_code, 200)
        self.assertContains(history, "Status events")
        self.assertEqual(
            excel["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertEqual(pdf["Content-Type"], "application/pdf")

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
                cursor.execute(
                    "SELECT has_table_privilege("
                    "'erp_runtime', 'loan_status_history', 'INSERT'), "
                    "has_table_privilege("
                    "'erp_runtime', 'loan_status_history', 'UPDATE'), "
                    "has_table_privilege("
                    "'erp_runtime', 'loan_status_history', 'DELETE')"
                )
                self.assertEqual(cursor.fetchone(), (True, False, False))
                cursor.execute(
                    "SELECT has_table_privilege("
                    "'erp_runtime', 'loan_approval_tiers', 'UPDATE'), "
                    "has_table_privilege("
                    "'erp_runtime', 'loan_approval_tiers', 'DELETE'), "
                    "has_column_privilege("
                    "'erp_runtime', 'loans', 'effective_annual_rate', 'UPDATE')"
                )
                self.assertEqual(cursor.fetchone(), (True, False, True))
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

    def test_branch_scope_blocks_forged_ids_for_loan_lifecycle_routes(self):
        other_branch = Branch.unscoped.create(
            name="Other Loan Workflow Branch",
            code="OLWB",
        )
        user_model = get_user_model()
        other_maker = user_model.objects.create_user(
            username="other-loan-maker",
            password="A-strong-test-password-123",  # nosec B106 - isolated test account
            branch=other_branch,
        )
        other_checker = user_model.objects.create_user(
            username="other-loan-checker",
            password="A-strong-test-password-123",  # nosec B106 - isolated test account
            branch=other_branch,
        )
        other_writeoff_checker = user_model.objects.create_user(
            username="other-loan-writeoff",
            password="A-strong-test-password-123",  # nosec B106 - isolated test account
            branch=other_branch,
        )
        other_member = Member.unscoped.create(
            branch=other_branch,
            member_code="OLWB-0001",
            first_name="Other",
            last_name="Borrower",
            status=Member.STATUS_ACTIVE,
        )
        MemberKYC.objects.create(
            member=other_member,
            document_type=MemberKYC.DOC_TYPE_NATIONAL_ID,
            status=MemberKYC.STATUS_VERIFIED,
            is_verified=True,
            verified_by=other_checker,
        )
        request = RequestFactory().post("/loans/applications/")
        request.active_branch_id = other_branch.pk
        branch_token = current_branch_id_var.set(other_branch.pk)
        user_token = current_user_var.set(other_maker)
        try:
            request.user = other_maker
            service = LoanService(request)
            application = service.create_application(
                branch_id=other_branch.pk,
                member_id=other_member.pk,
                product_id=self.product.pk,
                amount=Decimal("12000.00"),
                term=12,
                purpose="Other branch loan",
                idempotency_key=uuid.uuid4(),
            )
            service.submit(application_id=application.pk)
            request.user = other_checker
            current_user_var.set(other_checker)
            service.review(
                application_id=application.pk,
                decision=LoanApplication.STATUS_APPROVED,
                comment="Approved in the other branch.",
            )
            request.user = other_maker
            current_user_var.set(other_maker)
            loan = service.disburse(
                application_id=application.pk,
                disbursement_date=date(2025, 1, 15),
                channel="cash_in_hand",
                idempotency_key=uuid.uuid4(),
            )
            first_installment = LoanInstallment.objects.get(
                loan=loan,
                schedule_version=loan.schedule_version,
                number=1,
            )
            request.user = other_checker
            current_user_var.set(other_checker)
            service.repay(
                loan_id=loan.pk,
                amount=Decimal("1.00"),
                payment_date=first_installment.due_date,
                idempotency_key=uuid.uuid4(),
            )
            request.user = other_writeoff_checker
            current_user_var.set(other_writeoff_checker)
            service.write_off(
                loan_id=loan.pk,
                write_off_date=date(2025, 3, 1),
                reason="Test branch-scoped recovery route.",
                idempotency_key=uuid.uuid4(),
            )
        finally:
            current_user_var.reset(user_token)
            current_branch_id_var.reset(branch_token)

        self.maker.is_superuser = True
        self.maker.save(update_fields=["is_superuser"])
        self.client.force_login(self.maker)
        session = self.client.session
        session["active_branch_id"] = self.branch.pk
        session.save()

        for route_name in (
            "Module_Loans_applications",
            "Module_Loans_disbursements",
            "Module_Loans_repayments",
            "Module_Loans_portfolio",
            "Module_Loans_classification",
        ):
            with self.subTest(route_name=route_name):
                response = self.client.get(reverse(f"loans:{route_name}"))
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, other_member.member_code)

        detail_requests = [
            ("Module_Loans_application_submit", "post", application.pk),
            ("Module_Loans_application_review", "post", application.pk),
            ("Module_Loans_application_cancel", "post", application.pk),
            ("Module_Loans_disbursement_add", "post", application.pk),
            ("Module_Loans_repayment_add", "post", loan.pk),
            ("Module_Loans_reschedule", "post", loan.pk),
            ("Module_Loans_settle", "post", loan.pk),
            ("Module_Loans_waive_interest", "post", loan.pk),
            ("Module_Loans_write_off", "post", loan.pk),
            ("Module_Loans_recovery", "post", loan.pk),
            ("Module_Loans_schedule", "get", loan.pk),
            ("Module_Loans_statement", "get", loan.pk),
            ("Module_Loans_history", "get", loan.pk),
        ]
        for route_name, method, record_id in detail_requests:
            with self.subTest(route_name=route_name):
                response = getattr(self.client, method)(
                    reverse(f"loans:{route_name}", args=[record_id]),
                    {},
                )
                self.assertEqual(response.status_code, 404)

        self.assertEqual(
            Loan.unscoped.get(pk=loan.pk).status,
            Loan.STATUS_WRITTEN_OFF,
        )

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
            "Module_Loans_product_activate",
            "Module_Loans_product_deactivate",
            "Module_Loans_approval_tiers",
            "Module_Loans_approval_tier_add",
            "Module_Loans_approval_tier_edit",
            "Module_Loans_par_buckets",
            "Module_Loans_par_bucket_add",
            "Module_Loans_par_bucket_edit",
            "Module_Loans_classification",
            "Module_Loans_classification_excel",
            "Module_Loans_classification_pdf",
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
            "Module_Loans_statement",
            "Module_Loans_history",
            "Module_Loans_reschedule",
            "Module_Loans_settle",
            "Module_Loans_waive_interest",
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
            "Module_Loans_product_activate",
            "Module_Loans_product_deactivate",
        ):
            with self.subTest(route_name=route_name):
                response = self.client.get(
                    reverse(
                        f"loans:{route_name}",
                        args=[1] if "<int:pk>" in next(
                            route["url"]
                            for route in get_all_urls()
                            if route["route_name"] == route_name
                        ) else [],
                    )
                )
                self.assertEqual(response.status_code, 405)

    def test_loan_product_crud_status_filter_and_audit(self):
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        self.client.force_login(self.user)
        headers = {
            "HTTP_X_REQUESTED_WITH": "XMLHttpRequest",
            "HTTP_ACCEPT": "application/json",
        }
        product_data = {
            "code": "ROUTE-UI",
            "name": "Popup-managed loan product",
            "interest_method": LoanProduct.METHOD_FLAT,
            "annual_interest_rate": "12.0000",
            "min_amount": "100.00",
            "max_amount": "10000.00",
            "min_term": "1",
            "max_term": "24",
            "installment_frequency": LoanProduct.FREQUENCY_MONTHLY,
            "processing_fee": "0.00",
            "processing_fee_rate": "0.0000",
            "insurance_fee": "0.00",
            "insurance_fee_rate": "0.0000",
            "grace_period_days": "0",
            "late_penalty_rate": "0.0000",
            "penalty_grace_days": "0",
            "penalty_type": LoanProduct.PENALTY_PERCENT,
            "penalty_frequency": LoanProduct.PENALTY_DAILY,
            "penalty_cap_rate": "25.0000",
            "required_savings_rate": "0.0000",
            "max_concurrent_loans": "1",
            "cycle_limits": "{}",
            "early_settlement_fee": "0.00",
            "early_settlement_policy": LoanProduct.SETTLEMENT_WAIVE_UNEARNED,
            "overpayment_policy": LoanProduct.OVERPAYMENT_REFUND,
            "holiday_convention": LoanProduct.HOLIDAY_NEXT,
            "is_active": "on",
        }
        created = self.client.post(
            reverse("loans:Module_Loans_product_add") + "?popup=1",
            product_data,
            **headers,
        )
        self.assertEqual(created.status_code, 200)
        self.assertEqual(
            set(created.json()),
            {"success", "message", "data", "errors", "request_id"},
        )
        product = LoanProduct.objects.get(code="ROUTE-UI")

        invalid = self.client.post(
            reverse("loans:Module_Loans_product_edit", args=[product.pk])
            + "?popup=1",
            {**product_data, "min_amount": "500.00", "max_amount": "100.00"},
            **headers,
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertFalse(invalid.json()["success"])

        updated = self.client.post(
            reverse("loans:Module_Loans_product_edit", args=[product.pk])
            + "?popup=1",
            {**product_data, "name": "Updated loan product"},
            **headers,
        )
        self.assertEqual(updated.status_code, 200)
        product.refresh_from_db()
        self.assertEqual(product.name, "Updated loan product")
        update_audit = AuditLog.objects.get(
            entity_name="LoanProduct",
            entity_id=str(product.pk),
            action="Update",
        )
        self.assertEqual(update_audit.old_values["name"], "Popup-managed loan product")
        self.assertEqual(update_audit.new_values["name"], "Updated loan product")

        listed = self.client.get(
            reverse("loans:Module_Loans_products"),
            {"format": "json", "searchString": "ROUTE-UI", "status": "active"},
        )
        self.assertEqual(listed.json()["records"], 1)
        deactivated = self.client.post(
            reverse("loans:Module_Loans_product_deactivate", args=[product.pk]),
            **headers,
        )
        self.assertTrue(deactivated.json()["success"])
        status_audit = AuditLog.objects.get(
            entity_name="LoanProduct",
            entity_id=str(product.pk),
            action="Deactivate",
        )
        self.assertTrue(status_audit.old_values["is_active"])
        self.assertFalse(status_audit.new_values["is_active"])
        inactive = self.client.get(
            reverse("loans:Module_Loans_products"),
            {"format": "json", "status": "inactive"},
        )
        self.assertEqual(inactive.json()["records"], 1)
        self.client.post(
            reverse("loans:Module_Loans_product_activate", args=[product.pk]),
            **headers,
        )
        product.refresh_from_db()
        self.assertTrue(product.is_active)

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
