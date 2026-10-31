import uuid
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import get_resolver, reverse
from django.utils import timezone

from core.accounting.models import (
    Account,
    AccountingPeriod,
    FiscalYear,
    JournalEntry,
    SystemAccountMapping,
)
from core.branch.models import (
    Branch,
    Center,
    Member,
    Staff,
    UserBranchAccess,
)
from core.collections.models import CollectionSheet, CollectionSheetItem
from core.loans.models import Loan, LoanApplication, LoanInstallment, LoanProduct
from core.savings.models import SavingsProduct

from .middleware import AUTHENTICATED_ONLY_ROUTE_NAMES, PUBLIC_ROUTE_NAMES
from .models import Permission, Role, RolePermission, UserRole
from .permission_utils import get_all_urls, sync_permissions


class RoutePermissionTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name='Branch One', code='B001')
        self.other_branch = Branch.objects.create(name='Branch Two', code='B002')
        self.user = get_user_model().objects.create_user(
            username='rbac-test-user',
            password='A-strong-test-password-123',  # nosec B106 - isolated test account
            branch=self.branch,
        )
        UserBranchAccess.objects.create(user=self.user, branch=self.other_branch)
        self.client.force_login(self.user)
        sync_permissions()

    def grant_routes(self, *route_names):
        role = Role.objects.create(name=f'role-{Role.objects.count()}')
        for route_name in route_names:
            permission = Permission.objects.get(route_name=route_name)
            RolePermission.objects.create(role=role, permission=permission)
        UserRole.objects.create(user=self.user, role=role)

    def test_route_registry_excludes_public_and_authenticated_only_routes(self):
        route_names = {route['route_name'] for route in get_all_urls()}

        self.assertIn('Module_Auth_list_users', route_names)
        self.assertNotIn('Module_Auth_login', route_names)
        self.assertNotIn('Module_Auth_logout', route_names)
        self.assertNotIn('Module_Branch_switch', route_names)

    def test_every_module_route_is_classified(self):
        registered = {
            route_name
            for route_name in get_resolver().reverse_dict
            if isinstance(route_name, str) and route_name.startswith(('Module', 'API'))
        }
        permissioned = {route['route_name'] for route in get_all_urls()}
        classified = permissioned | PUBLIC_ROUTE_NAMES | AUTHENTICATED_ONLY_ROUTE_NAMES

        self.assertEqual(registered - classified, set())

    def test_authenticated_user_without_role_is_denied(self):
        response = self.client.get('/accounts/users/')

        self.assertEqual(response.status_code, 403)

    @override_settings(
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.redis.RedisCache",
                "LOCATION": "redis://127.0.0.1:1/0",
            }
        }
    )
    def test_permission_revocation_is_immediate_across_clients_with_shared_cache_config(self):
        self.grant_routes('Module_Auth_list_users')
        permission = Permission.objects.get(route_name='Module_Auth_list_users')
        role = UserRole.objects.get(user=self.user).role
        worker_one = Client()
        worker_two = Client()
        worker_one.force_login(self.user)
        worker_two.force_login(self.user)
        path = reverse('accounts:Module_Auth_list_users')

        self.assertEqual(worker_one.get(path).status_code, 200)
        self.assertEqual(worker_two.get(path).status_code, 200)

        RolePermission.objects.filter(role=role, permission=permission).delete()

        self.assertEqual(worker_two.get(path).status_code, 403)

    def test_existing_dashboard_renders_for_authenticated_user(self):
        response = self.client.get('/')

        self.assertEqual(response.status_code, 200)

    def test_dashboard_cards_match_branch_data_and_require_metric_permission(self):
        Member.unscoped.create(
            branch=self.branch,
            member_code='DASH-001',
            first_name='Active',
            last_name='Member',
            status=Member.STATUS_ACTIVE,
        )
        Member.unscoped.create(
            branch=self.other_branch,
            member_code='DASH-002',
            first_name='Other',
            last_name='Branch',
            status=Member.STATUS_ACTIVE,
        )
        UserBranchAccess.objects.filter(
            user=self.user, branch=self.other_branch
        ).delete()
        self.grant_routes('Module_Members_list')

        response = self.client.get('/')

        self.assertEqual(response.status_code, 200)
        cards = response.context['dashboard_cards']
        self.assertEqual(
            cards,
            [{'key': 'active_members', 'title': 'Active members', 'value': '1'}],
        )
        self.assertContains(response, 'Active members')
        self.assertNotContains(response, 'Savings balance')

    def _seed_dashboard_metrics(self, branch, *, suffix, members_count, savings_balance,
                                loan_values, collection_amount, pending_count):
        today = timezone.localdate()
        center = Center.unscoped.create(
            branch=branch,
            name=f'Dashboard Center {suffix}',
            code=f'DASH-CENTER-{suffix}',
        )
        staff = Staff.unscoped.create(
            branch=branch,
            full_name=f'Dashboard Officer {suffix}',
        )
        center.field_officer = staff
        center.save(update_fields=['field_officer'])
        members = [
            Member.unscoped.create(
                branch=branch,
                center=center,
                member_code=f'DASH-{suffix}-{index:03d}',
                first_name=f'Member{index}',
                last_name=suffix,
                status=Member.STATUS_ACTIVE,
            )
            for index in range(members_count)
        ]
        savings_product, _ = SavingsProduct.objects.get_or_create(
            code='DASH-SAV',
            defaults={
                'name': 'Dashboard savings',
                'savings_type': SavingsProduct.TYPE_GENERAL,
            },
        )
        from core.savings.models import SavingsAccount

        account = SavingsAccount(
            branch=branch,
            product=savings_product,
            member=members[0],
            account_number=f'DASH-{suffix}-SAV',
            status=SavingsAccount.STATUS_ACTIVE,
            balance=Decimal(savings_balance),
            opened_at=today,
            created_by=self.user,
        )
        account._savings_update_authorized = True
        account.save()

        loan_product, _ = LoanProduct.objects.get_or_create(
            code='DASH-LOAN',
            defaults={
                'name': 'Dashboard loan',
                'interest_method': LoanProduct.METHOD_FLAT,
                'annual_interest_rate': 0,
                'min_amount': 1,
                'max_amount': 100000,
                'min_term': 1,
                'max_term': 12,
                'installment_frequency': LoanProduct.FREQUENCY_MONTHLY,
            },
        )
        fiscal_year = FiscalYear.objects.create(
            name=f'Dashboard FY {suffix}',
            start_date=date(2020, 1, 1),
            end_date=date(2100, 12, 31),
        )
        period = AccountingPeriod.objects.create(
            fiscal_year=fiscal_year,
            number=1,
            name='Dashboard annual period',
            start_date=date(2020, 1, 1),
            end_date=date(2100, 12, 31),
        )
        journal = JournalEntry.unscoped.create(
            branch=branch,
            fiscal_year=fiscal_year,
            period=period,
            voucher_type='journal',
            voucher_number=f'DASH-{suffix}',
            journal_date=today,
            narration='Dashboard fixture',
            created_by=self.user,
        )
        for index, (principal, outstanding, overdue_amount, days_overdue) in enumerate(
            loan_values
        ):
            application = LoanApplication.unscoped.create(
                branch=branch,
                member=members[index % len(members)],
                product=loan_product,
                requested_amount=Decimal(principal),
                approved_amount=Decimal(principal),
                term=1,
                purpose='Dashboard fixture',
                status=LoanApplication.STATUS_DISBURSED,
                created_by=self.user,
            )
            loan = Loan.unscoped.create(
                branch=branch,
                application=application,
                member=application.member,
                product=loan_product,
                principal=Decimal(principal),
                outstanding_principal=Decimal(outstanding),
                status=Loan.STATUS_ACTIVE,
                disbursed_at=today,
                disbursed_by=self.user,
                journal_entry=journal,
                idempotency_key=uuid.uuid4(),
            )
            LoanInstallment.objects.create(
                loan=loan,
                schedule_version=loan.schedule_version,
                number=1,
                due_date=today - timedelta(days=days_overdue),
                principal_due=Decimal(overdue_amount),
                interest_due=Decimal('0.00'),
                fee_due=Decimal('0.00'),
            )

        sheet = CollectionSheet.unscoped.create(
            branch=branch,
            center=center,
            field_officer=staff,
            collection_date=today,
            idempotency_key=uuid.uuid4(),
            generated_by=self.user,
        )
        CollectionSheetItem.unscoped.create(
            branch=branch,
            sheet=sheet,
            member=members[0],
            collected_amount=Decimal(collection_amount),
            savings_amount=Decimal('0.00'),
        )
        for status in (
            CollectionSheet.STATUS_IN_PROGRESS,
            CollectionSheet.STATUS_SUBMITTED,
            CollectionSheet.STATUS_RECONCILED,
            CollectionSheet.STATUS_POSTED,
        ):
            sheet.status = status
            if status == CollectionSheet.STATUS_POSTED:
                sheet.posted_by = self.user
                sheet.posted_at = timezone.now()
            sheet.save()
        for index in range(pending_count):
            LoanApplication.unscoped.create(
                branch=branch,
                member=members[index % len(members)],
                product=loan_product,
                requested_amount=Decimal('10.00'),
                term=1,
                purpose='Pending dashboard approval',
                status=LoanApplication.STATUS_SUBMITTED,
                created_by=self.user,
            )

    def test_dashboard_has_seeded_metrics_for_every_card(self):
        UserBranchAccess.objects.filter(user=self.user).delete()
        self._seed_dashboard_metrics(
            self.branch,
            suffix='ONE',
            members_count=1,
            savings_balance='250.00',
            loan_values=[
                ('1000.00', '500.00', '100.00', 5),
                ('500.00', '250.00', '50.00', 40),
                ('200.00', '100.00', '25.00', 100),
            ],
            collection_amount='150.00',
            pending_count=1,
        )
        self.grant_routes(
            'Module_Members_list',
            'Module_Savings_balance_report',
            'Module_Loans_portfolio',
            'Module_Collections_report_daily',
            'Module_Loans_applications',
        )

        response = self.client.get('/')

        self.assertEqual(response.status_code, 200)
        cards = {
            card['key']: card['value']
            for card in response.context['dashboard_cards']
        }
        self.assertEqual(
            cards,
            {
                'active_members': '1',
                'savings_balance': '250.00',
                'loans_outstanding': '850.00',
                'overdue_amount': '175.00',
                'par_1': '50.00',
                'par_30': '20.59',
                'par_90': '5.88',
                'todays_collection': '150.00',
                'pending_approvals': '1',
            },
        )

    def test_dashboard_metric_cards_exclude_other_branch_data(self):
        UserBranchAccess.objects.filter(user=self.user).delete()
        self._seed_dashboard_metrics(
            self.branch,
            suffix='ONE',
            members_count=1,
            savings_balance='250.00',
            loan_values=[('1000.00', '500.00', '100.00', 5)],
            collection_amount='150.00',
            pending_count=1,
        )
        self._seed_dashboard_metrics(
            self.other_branch,
            suffix='TWO',
            members_count=2,
            savings_balance='800.00',
            loan_values=[('2000.00', '1200.00', '400.00', 100)],
            collection_amount='900.00',
            pending_count=3,
        )
        self.grant_routes(
            'Module_Members_list',
            'Module_Savings_balance_report',
            'Module_Loans_portfolio',
            'Module_Collections_report_daily',
            'Module_Loans_applications',
        )

        response = self.client.get('/')

        cards = {
            card['key']: card['value']
            for card in response.context['dashboard_cards']
        }
        self.assertEqual(cards['active_members'], '1')
        self.assertEqual(cards['savings_balance'], '250.00')
        self.assertEqual(cards['loans_outstanding'], '500.00')
        self.assertEqual(cards['overdue_amount'], '100.00')
        self.assertEqual(cards['par_1'], '50.00')
        self.assertEqual(cards['par_30'], '0.00')
        self.assertEqual(cards['par_90'], '0.00')
        self.assertEqual(cards['todays_collection'], '150.00')
        self.assertEqual(cards['pending_approvals'], '1')

    def test_assigned_role_grants_only_its_active_route(self):
        self.grant_routes('Module_Auth_list_users')

        allowed_response = self.client.get('/accounts/users/')
        denied_response = self.client.get('/accounts/roles/')

        self.assertEqual(allowed_response.status_code, 200)
        self.assertEqual(denied_response.status_code, 403)

    def test_inactive_route_permission_is_denied(self):
        role = Role.objects.create(name='Inactive route role')
        permission = Permission.objects.get(route_name='Module_Auth_list_users')
        permission.is_active = False
        permission.save(update_fields=['is_active'])
        RolePermission.objects.create(role=role, permission=permission)
        UserRole.objects.create(user=self.user, role=role)

        response = self.client.get('/accounts/users/')

        self.assertEqual(response.status_code, 403)

    def test_user_creation_persists_primary_and_explicit_branch_access(self):
        self.grant_routes('Module_Auth_create_user')
        response = self.client.post('/accounts/create-user/', {
            'username': 'branch-user',
            'email': 'branch-user@example.test',
            'first_name': 'Branch',
            'last_name': 'User',
            'password': 'S!rong-and-unique-pass-451',
            'confirm_password': 'S!rong-and-unique-pass-451',
            'role_id': '',
            'branch': str(self.other_branch.pk),
            'accessible_branches': [str(self.branch.pk)],
        })

        self.assertEqual(response.status_code, 302)
        created_user = get_user_model().objects.get(username='branch-user')
        self.assertEqual(created_user.branch_id, self.other_branch.pk)
        self.assertEqual(
            set(created_user.branch_access.values_list('branch_id', flat=True)),
            {self.branch.pk},
        )

    def test_user_edit_does_not_allow_privilege_flag_escalation(self):
        self.grant_routes('Module_Auth_edit_user')
        target = get_user_model().objects.create_user(
            username='editable-user',
            password='A-strong-test-password-123',  # nosec B106 - isolated test account
            branch=self.branch,
        )
        response = self.client.post(f'/accounts/users/edit/{target.pk}/', {
            'username': target.username,
            'email': 'editable@example.test',
            'first_name': 'Editable',
            'last_name': 'User',
            'branch': str(self.branch.pk),
            'role_id': '',
            'is_staff': 'on',
            'is_superuser': 'on',
        })

        target.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertFalse(target.is_staff)
        self.assertFalse(target.is_superuser)


class PopupWorkflowTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name='Popup Branch', code='POP')
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username='popup-user',
            password='A-strong-test-password-123',  # nosec B106 - isolated test account
            branch=self.branch,
        )
        self.member = Member.unscoped.create(
            branch=self.branch,
            member_code='POP-0001',
            first_name='Popup',
            last_name='Member',
        )
        self.savings_product = SavingsProduct.objects.create(
            code='POP-SAV',
            name='Popup savings',
            savings_type=SavingsProduct.TYPE_GENERAL,
        )
        self.loan_product = LoanProduct.objects.create(
            code='POP-LOAN',
            name='Popup loan',
            interest_method=LoanProduct.METHOD_FLAT,
            annual_interest_rate=1,
            min_amount=1,
            max_amount=100,
            min_term=1,
            max_term=12,
            installment_frequency=LoanProduct.FREQUENCY_MONTHLY,
        )
        self.role = Role.objects.create(name='Popup role')
        self.editable_user = user_model.objects.create_user(
            username='popup-editable-user',
            password='A-strong-test-password-123',  # nosec B106 - isolated test account
            branch=self.branch,
        )
        self.account = Account.objects.create(
            code='POP-100',
            name='Popup account',
            account_type=Account.ASSET,
            normal_balance=Account.DEBIT,
        )
        self.system_mapping = SystemAccountMapping.objects.create(
            key='cash_in_hand',
            account=self.account,
        )
        self.superuser = user_model.objects.create_superuser(
            username='popup-admin',
            password='A-strong-test-password-123',  # nosec B106 - isolated test account
            branch=self.branch,
        )
        sync_permissions()

    def popup_urls(self):
        return [
            reverse('branch:Module_Branch_add_branch'),
            reverse('branch:Module_Branch_edit_branch', args=[self.branch.pk]),
            reverse('branch:Module_Members_add'),
            reverse('branch:Module_Members_edit', args=[self.member.pk]),
            reverse('accounts:Module_Auth_create_role'),
            reverse('accounts:Module_Auth_edit_role', args=[self.role.pk]),
            reverse('accounts:Module_Auth_create_user'),
            reverse('accounts:Module_Auth_edit_user', args=[self.editable_user.pk]),
            reverse('savings:Module_Savings_product_add'),
            reverse('savings:Module_Savings_product_edit', args=[self.savings_product.pk]),
            reverse('savings:Module_Savings_account_add'),
            reverse('savings:Module_Savings_deposit'),
            reverse('savings:Module_Savings_withdraw'),
            reverse('savings:Module_Savings_fee'),
            reverse('savings:Module_Savings_interest'),
            reverse('loans:Module_Loans_product_add'),
            reverse('loans:Module_Loans_product_edit', args=[self.loan_product.pk]),
            reverse('loans:Module_Loans_application_add'),
            reverse('accounting:Module_Accounting_account_add'),
            reverse('accounting:Module_Accounting_account_edit', args=[self.account.pk]),
            reverse('accounting:Module_Accounting_fiscal_year_add'),
            reverse('accounting:Module_Accounting_period_add'),
            reverse('accounting:Module_Accounting_system_account_add'),
            reverse(
                'accounting:Module_Accounting_system_account_edit',
                args=[self.system_mapping.pk],
            ),
            reverse('accounting:Module_Accounting_journal_add'),
        ]

    def test_ajax_popup_routes_return_fragments_and_keep_frame_denial(self):
        self.client.force_login(self.superuser)
        for url in self.popup_urls():
            with self.subTest(url=url):
                response = self.client.get(
                    f'{url}?popup=1',
                    HTTP_X_REQUESTED_WITH='XMLHttpRequest',
                    HTTP_ACCEPT='text/html',
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response['Content-Type'].split(';')[0], 'text/html')
                self.assertEqual(response['X-Frame-Options'], 'DENY')
                self.assertNotIn(b'<!DOCTYPE html>', response.content)
                self.assertIn(b'<form', response.content)

    def test_popup_routes_require_login_and_route_permission(self):
        for url in self.popup_urls():
            with self.subTest(url=url, access='anonymous'):
                response = Client().get(
                    f'{url}?popup=1',
                    HTTP_X_REQUESTED_WITH='XMLHttpRequest',
                )
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json()['success'], False)

            with self.subTest(url=url, access='without-permission'):
                self.client.force_login(self.user)
                response = self.client.get(
                    f'{url}?popup=1',
                    HTTP_X_REQUESTED_WITH='XMLHttpRequest',
                )
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json()['success'], False)

    def test_popup_save_uses_standard_json_envelope_for_success_and_validation(self):
        self.client.force_login(self.superuser)
        url = f"{reverse('accounts:Module_Auth_create_role')}?popup=1"
        headers = {
            'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest',
            'HTTP_ACCEPT': 'application/json',
        }
        response = self.client.post(url, {'name': 'Popup reviewer'}, **headers)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            set(response.json()),
            {'success', 'message', 'data', 'errors', 'request_id'},
        )
        self.assertTrue(response.json()['success'])
        self.assertEqual(response.json()['data']['id'], Role.objects.get(name='Popup reviewer').pk)

        invalid = self.client.post(url, {'name': ''}, **headers)

        self.assertEqual(invalid.status_code, 400)
        self.assertFalse(invalid.json()['success'])
        self.assertIn('name', invalid.json()['errors'])
