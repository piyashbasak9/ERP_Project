from django.contrib.auth import get_user_model
from django.test import TestCase

from core.branch.models import Branch

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
