from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import get_resolver

from core.branch.models import Branch, UserBranchAccess

from .middleware import AUTHENTICATED_ONLY_ROUTE_NAMES, PUBLIC_ROUTE_NAMES
from .models import Permission, Role, RolePermission, UserRole
from .permission_utils import get_all_urls, sync_permissions


class RoutePermissionTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name='Branch One', code='B001')
        self.other_branch = Branch.objects.create(name='Branch Two', code='B002')
        self.user = get_user_model().objects.create_user(
            username='rbac-test-user',
            password='A-strong-test-password-123',
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
            password='A-strong-test-password-123',
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
