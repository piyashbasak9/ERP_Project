from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import get_resolver, reverse

from core.accounting.models import Account, SystemAccountMapping
from core.branch.models import Branch, Member, UserBranchAccess
from core.loans.models import LoanProduct
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
