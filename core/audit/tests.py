from django.contrib.auth import get_user_model
from django.db import DatabaseError, connection, transaction
from django.test import Client, TestCase
from django.urls import reverse

from core.accounts.models import Permission, Role, RolePermission, UserRole
from core.accounts.permission_utils import sync_permissions
from core.branch.models import Branch, Member, UserBranchAccess

from .context import audit_context_var
from .models import AuditLog
from .services import log_action


class AuditLogTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name='Audit Branch', code='AUDIT')
        self.user = get_user_model().objects.create_user(
            username='audit-test-user',
            password='A-strong-test-password-123',  # nosec B106 - isolated test account
            branch=self.branch,
        )

    def test_log_action_redacts_sensitive_values(self):
        token = audit_context_var.set({'user': self.user, 'branch_id': self.branch.pk})
        try:
            log = log_action(
                'Update',
                'Member',
                '1',
                new_values={
                    'national_id': '123456789',
                    'phone_number': '5551234',
                    'status': 'active',
                },
            )
        finally:
            audit_context_var.reset(token)

        self.assertEqual(log.new_values['national_id'], '[REDACTED]')
        self.assertEqual(log.new_values['phone_number'], '[REDACTED]')
        self.assertEqual(log.new_values['status'], 'active')

    def test_audit_entries_cannot_be_updated_or_deleted_through_orm(self):
        log = AuditLog.objects.create(
            user=self.user,
            branch=self.branch,
            action='Create',
            entity_name='Member',
        )

        with self.assertRaises(TypeError):
            AuditLog.objects.filter(pk=log.pk).update(action='Delete')
        with self.assertRaises(TypeError):
            log.save()
        with self.assertRaises(TypeError):
            log.delete()

    def test_postgresql_trigger_rejects_direct_audit_log_mutation(self):
        log = AuditLog.objects.create(
            user=self.user,
            branch=self.branch,
            action="Create",
            entity_name="Member",
        )

        with (
            self.assertRaises(DatabaseError),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(
                "UPDATE audit_logs SET action = %s WHERE id = %s",
                ["Delete", log.pk],
            )


class AuditScreenTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name="Audit Scope One", code="AUD1")
        self.other_branch = Branch.objects.create(name="Audit Scope Two", code="AUD2")
        self.user = get_user_model().objects.create_user(
            username="audit-screen-user",
            password="A-strong-test-password-123",
            branch=self.branch,
        )
        self.client = Client()
        self.client.force_login(self.user)
        sync_permissions()

    def grant_routes(self, *route_names):
        role = Role.objects.create(name=f"audit-role-{Role.objects.count()}")
        for route_name in route_names:
            permission = Permission.objects.get(route_name=route_name)
            RolePermission.objects.create(role=role, permission=permission)
        UserRole.objects.create(user=self.user, role=role)

    def test_audit_screens_and_record_trail_require_permissions(self):
        routes = (
            ("Module_Audit_logs", "audit:Module_Audit_logs", {}),
            ("Module_Audit_events", "audit:Module_Audit_events", {}),
            ("Module_Audit_dashboard", "audit:Module_Audit_dashboard", {}),
            (
                "Module_Audit_trail",
                "audit:Module_Audit_trail",
                {"entity": "Loan", "entity_id": "1"},
            ),
        )
        for route_name, reverse_name, kwargs in routes:
            with self.subTest(route=route_name):
                response = self.client.get(reverse(reverse_name, kwargs=kwargs))
                self.assertEqual(response.status_code, 403)

    def test_audit_search_and_activity_dashboard_are_branch_scoped(self):
        UserBranchAccess.objects.filter(user=self.user).delete()
        AuditLog.objects.create(
            user=self.user,
            user_name=self.user.username,
            branch=self.branch,
            action="Update",
            entity_name="Loan",
            entity_id="17",
        )
        AuditLog.objects.create(
            branch=self.other_branch,
            action="Login",
            entity_name="User",
            entity_id="outside",
        )
        self.grant_routes("Module_Audit_logs", "Module_Audit_dashboard")

        logs_response = self.client.get(
            reverse("audit:Module_Audit_logs"),
            {"action": "Update", "entity": "Loan", "branch": self.branch.pk},
        )
        dashboard_response = self.client.get(reverse("audit:Module_Audit_dashboard"))

        self.assertEqual(logs_response.status_code, 200)
        self.assertEqual(logs_response.context["page_obj"].paginator.count, 1)
        self.assertEqual(dashboard_response.status_code, 200)
        self.assertEqual(
            sum(row["count"] for row in dashboard_response.context["logins_per_day"]),
            1,
        )

    def test_axes_lockout_signal_creates_audited_system_activity(self):
        from axes.signals import user_locked_out

        user_locked_out.send(
            sender=None,
            request=None,
            username=self.user.username,
            ip_address="192.0.2.10",
        )

        self.assertTrue(
            AuditLog.objects.filter(
                action="Lockout",
                entity_name="User",
                entity_id=self.user.username,
                branch=self.branch,
            ).exists()
        )

    def test_member_sensitive_read_is_audited_without_copying_identifier_values(self):
        member = Member.unscoped.create(
            branch=self.branch,
            member_code="AUD-MEMBER-1",
            first_name="Sensitive",
            last_name="Member",
            national_id="NATIONAL-ID-SECRET",
        )
        self.grant_routes("Module_Members_detail")

        response = self.client.get(
            reverse("branch:Module_Members_detail", args=[member.pk])
        )

        self.assertEqual(response.status_code, 200)
        audit = AuditLog.objects.get(
            action="ViewSensitiveData",
            entity_name="Member",
            entity_id=str(member.pk),
        )
        self.assertEqual(
            audit.new_values["fields"],
            ["national_id", "other_id_numbers"],
        )
        self.assertNotIn("NATIONAL-ID-SECRET", str(audit.new_values))
