import smtplib
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from core.accounts.models import Permission, Role, RolePermission, UserRole
from core.audit.models import AuditLog
from core.branch.models import Branch

from .models import (
    Notification,
    NotificationPreference,
    NotificationTemplate,
)
from .services import (
    _create_for_event,
    generate_daily_notifications,
    run_notification_job,
)


class NotificationServiceTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name="Notification Branch", code="NTF")
        self.other_branch = Branch.objects.create(
            name="Other Notification Branch", code="NTF2"
        )
        self.user = get_user_model().objects.create_user(
            username="notification-user",
            password="A-strong-test-password-123",  # nosec B106 - isolated test account
            email="notification@example.test",
            branch=self.branch,
        )
        role = Role.objects.create(name="notification-role")
        UserRole.objects.create(user=self.user, role=role)
        approval_permission = Permission.objects.create(
            route_name="Module_Loans_application_approve",
            url_pattern="/notification-test/approval/",
        )
        RolePermission.objects.create(role=role, permission=approval_permission)
        self.context = {
            "branch_name": self.branch.name,
            "due_date": "2026-11-03",
            "amount": "100.00",
            "member_name": "Test Member",
            "reference": "LN-1",
            "days": 3,
        }

    def create_event(self, *, branch_id=None, event_reference="installment:1"):
        return _create_for_event(
            event_key="installment_due",
            event_reference=event_reference,
            branch_id=branch_id or self.branch.pk,
            event_date=timezone.localdate(),
            context=self.context,
        )

    def test_notification_generation_is_idempotent_per_recipient_event_and_day(self):
        self.assertEqual(self.create_event(), 2)
        self.assertEqual(self.create_event(), 0)
        self.assertEqual(
            Notification.objects.filter(
                recipient=self.user,
                event_key="installment_due",
                event_reference="installment:1",
                event_date=timezone.localdate(),
            ).count(),
            2,
        )

    def test_notification_opt_out_is_respected(self):
        NotificationPreference.objects.create(
            user=self.user,
            email_enabled=False,
            in_app_enabled=False,
        )

        self.assertEqual(self.create_event(), 0)
        self.assertFalse(Notification.objects.exists())

    def test_sms_uses_console_provider_without_logging_recipient_data(self):
        NotificationPreference.objects.create(
            user=self.user,
            email_enabled=False,
            in_app_enabled=False,
            sms_enabled=True,
        )

        self.assertEqual(self.create_event(), 1)
        with self.assertLogs(
            "core.notifications.providers", level="INFO"
        ) as captured:
            result = run_notification_job(now=timezone.now())

        notification = Notification.objects.get(channel=Notification.CHANNEL_SMS)
        self.assertEqual(result["sent"], 1)
        self.assertEqual(notification.status, Notification.STATUS_SENT)
        self.assertNotIn(self.user.username, str(captured.output))
        self.assertNotIn(self.user.email, str(captured.output))

    def test_recipients_are_limited_to_the_event_branch(self):
        other_user = get_user_model().objects.create_user(
            username="other-branch-user",
            password="A-strong-test-password-123",  # nosec B106 - isolated test account
            email="other@example.test",
            branch=self.other_branch,
        )
        role = Role.objects.create(name="other-notification-role")
        UserRole.objects.create(user=other_user, role=role)

        self.create_event()

        self.assertEqual(
            set(Notification.objects.values_list("recipient_id", flat=True)),
            {self.user.pk},
        )

    def test_template_placeholders_are_validated(self):
        template = NotificationTemplate(
            event_key="installment_due",
            subject="Due {unknown}",
            body="Installment {reference}",
        )

        with self.assertRaises(ValidationError):
            template.full_clean()

    def test_daily_job_generates_all_four_event_types(self):
        today = timezone.localdate()
        loan = SimpleNamespace(
            branch_id=self.branch.pk,
            branch=self.branch,
            member=SimpleNamespace(full_name="Test Member"),
            schedule_version=1,
        )
        due_installment = SimpleNamespace(
            pk=11,
            loan=loan,
            loan_id=71,
            due_date=today + timedelta(days=3),
            total_due=Decimal("10.00"),
            number=1,
        )
        overdue_installment = SimpleNamespace(
            pk=12,
            loan=loan,
            loan_id=71,
            due_date=today - timedelta(days=1),
            total_due=Decimal("15.00"),
            number=2,
        )
        application = SimpleNamespace(
            pk=81,
            branch_id=self.branch.pk,
            branch=self.branch,
            updated_at=timezone.now(),
        )
        document = SimpleNamespace(
            pk=91,
            member=SimpleNamespace(
                branch_id=self.branch.pk,
                branch=self.branch,
                full_name="Test Member",
            ),
            get_document_type_display=lambda: "National ID",
        )
        due_query = SimpleNamespace(select_related=lambda *args: [due_installment])
        overdue_query = SimpleNamespace(
            filter=lambda *args: SimpleNamespace(
                select_related=lambda *related: [overdue_installment]
            )
        )
        approvals_query = SimpleNamespace(
            select_related=lambda *args: [application]
        )
        documents_query = SimpleNamespace(
            select_related=lambda *args: [document]
        )

        with (
            patch(
                "core.notifications.services.NotificationConfiguration.current",
                return_value=SimpleNamespace(installment_days_before=3),
            ),
            patch(
                "core.notifications.services.LoanInstallment.objects.filter",
                side_effect=[
                    due_query,
                    overdue_query,
                    due_query,
                    overdue_query,
                ],
            ),
            patch(
                "core.notifications.services.LoanApplication.objects.filter",
                return_value=approvals_query,
            ),
            patch(
                "core.notifications.services.MemberKYC.objects.filter",
                return_value=documents_query,
            ),
        ):
            generate_daily_notifications(today=today)
            generate_daily_notifications(today=today)

        self.assertEqual(
            set(Notification.objects.values_list("event_key", flat=True)),
            {"installment_due", "overdue", "approval_waiting", "kyc_expiry"},
        )
        self.assertEqual(Notification.objects.count(), 8)

    def test_provider_failure_retries_and_records_job_and_integration_events(self):
        NotificationPreference.objects.create(
            user=self.user,
            email_enabled=True,
            in_app_enabled=False,
        )
        self.create_event()
        now = timezone.now()

        class FailingProvider:
            def send(self, notification):
                raise smtplib.SMTPException("private provider details")

        with patch("core.notifications.services.provider_for", return_value=FailingProvider()):
            result = run_notification_job(today=timezone.localdate(), now=now)

        delivery = Notification.objects.get(channel=Notification.CHANNEL_EMAIL)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(delivery.attempts, 1)
        self.assertGreater(delivery.retry_at, now)
        self.assertTrue(
            AuditLog.objects.filter(
                action="SystemEvent",
                new_values__category="integration",
            ).exists()
        )
        self.assertGreaterEqual(
            AuditLog.objects.filter(
                action="SystemEvent",
                new_values__category="job",
            ).count(),
            2,
        )
        event_messages = list(
            AuditLog.objects.filter(action="SystemEvent").values_list(
                "new_values", flat=True
            )
        )
        self.assertNotIn("notification@example.test", str(event_messages))
        self.assertNotIn("private provider details", str(event_messages))

    def test_delivery_respects_opt_out_changed_after_notification_creation(self):
        NotificationPreference.objects.create(
            user=self.user,
            email_enabled=True,
            in_app_enabled=False,
        )
        self.create_event()
        NotificationPreference.objects.filter(user=self.user).update(
            email_enabled=False
        )

        with patch("core.notifications.services.provider_for") as provider:
            result = run_notification_job(now=timezone.now())

        notification = Notification.objects.get(channel=Notification.CHANNEL_EMAIL)
        self.assertEqual(result["sent"], 0)
        self.assertEqual(notification.status, Notification.STATUS_CANCELLED)
        provider.assert_not_called()

    def test_unexpected_job_failure_is_recorded_and_propagated(self):
        with (
            patch(
                "core.notifications.services.generate_daily_notifications",
                side_effect=RuntimeError("private failure"),
            ),
            self.assertRaisesMessage(RuntimeError, "private failure"),
        ):
            run_notification_job()

        events = list(
            AuditLog.objects.filter(
                action="SystemEvent",
                entity_id="job",
            ).values_list("new_values", flat=True)
        )
        self.assertTrue(
            any(
                event["status"] == "failed"
                and "RuntimeError" in event["message"]
                for event in events
            )
        )
        self.assertNotIn(
            "private failure",
            str(
                AuditLog.objects.filter(action="SystemEvent").values_list(
                    "new_values", flat=True
                )
            ),
        )


class NotificationRouteTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name="Notification Route Branch", code="NTR")
        self.user = get_user_model().objects.create_user(
            username="notification-route-user",
            password="A-strong-test-password-123",  # nosec B106 - isolated test account
            branch=self.branch,
        )
        self.client = Client()
        self.client.force_login(self.user)

    def grant_routes(self, *route_names):
        role = Role.objects.create(name=f"notification-route-role-{Role.objects.count()}")
        for route_name in route_names:
            permission, _ = Permission.objects.get_or_create(
                route_name=route_name,
                defaults={
                    "url_pattern": f"/notification-test/{route_name}/",
                    "module": "Notifications",
                    "action": "test",
                },
            )
            RolePermission.objects.create(role=role, permission=permission)
        UserRole.objects.update_or_create(user=self.user, defaults={"role": role})

    def test_every_notification_route_requires_its_permission(self):
        routes = (
            ("GET", "notifications:Module_Notifications_list", {}),
            ("GET", "notifications:Module_Notifications_preferences", {}),
            (
                "POST",
                "notifications:Module_Notifications_preferences_save",
                {},
            ),
            ("POST", "notifications:Module_Notifications_mark_read", {"pk": 1}),
            (
                "GET",
                "configuration:Module_Settings_notification_templates",
                {},
            ),
            (
                "POST",
                "configuration:Module_Settings_notification_template_save",
                {},
            ),
            (
                "POST",
                "configuration:Module_Settings_notification_schedule_save",
                {},
            ),
        )
        for method, route_name, kwargs in routes:
            with self.subTest(route=route_name):
                response = getattr(self.client, method.lower())(
                    reverse(route_name, kwargs=kwargs)
                )
                self.assertEqual(response.status_code, 403)

    def test_notification_mutation_routes_reject_get(self):
        mutation_routes = (
            "notifications:Module_Notifications_preferences_save",
            "notifications:Module_Notifications_mark_read",
            "configuration:Module_Settings_notification_template_save",
            "configuration:Module_Settings_notification_schedule_save",
        )
        self.grant_routes(
            "Module_Notifications_preferences_save",
            "Module_Notifications_mark_read",
            "Module_Settings_notification_template_save",
            "Module_Settings_notification_schedule_save",
        )
        for route_name in mutation_routes:
            kwargs = {"pk": 1} if route_name.endswith("mark_read") else {}
            with self.subTest(route=route_name):
                response = self.client.get(reverse(route_name, kwargs=kwargs))
                self.assertEqual(response.status_code, 405)

    def test_settings_reject_invalid_notification_placeholders(self):
        self.grant_routes("Module_Settings_notification_template_save")
        response = self.client.post(
            reverse("configuration:Module_Settings_notification_template_save"),
            {
                "event_key": "installment_due",
                "subject": "{private_data}",
                "body": "Body {reference}",
                "enabled": "on",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(NotificationTemplate.objects.exists())
