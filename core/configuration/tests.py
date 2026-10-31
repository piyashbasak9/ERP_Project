from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from core.accounts.models import Permission, Role, RolePermission, UserRole
from core.accounts.permission_utils import sync_permissions
from core.audit.models import AuditLog
from core.branch.models import Branch
from core.common.templatetags.user_formatting import config_money, user_date

from .models import SystemConfiguration, UserPreference
from .services import get_system_configuration


class ConfigurationRouteTests(TestCase):
    def setUp(self):
        cache.clear()
        self.branch = Branch.objects.create(name="Configuration Branch", code="CFG")
        self.user = get_user_model().objects.create_user(
            username="configuration-test-user",
            password="A-strong-test-password-123",
            branch=self.branch,
        )
        self.client.force_login(self.user)
        sync_permissions()

    def grant_routes(self, *route_names):
        role = Role.objects.create(name=f"configuration-role-{Role.objects.count()}")
        for route_name in route_names:
            permission = Permission.objects.get(route_name=route_name)
            RolePermission.objects.create(role=role, permission=permission)
        UserRole.objects.create(user=self.user, role=role)

    def test_settings_screens_and_mutations_require_their_own_permission(self):
        routes = (
            ("Module_Settings_index", "GET", "configuration:Module_Settings_index"),
            ("Module_Settings_system", "GET", "configuration:Module_Settings_system"),
            ("Module_Settings_system_save", "POST", "configuration:Module_Settings_system_save"),
            ("Module_Settings_organization", "GET", "configuration:Module_Settings_organization"),
            ("Module_Settings_organization_save", "POST", "configuration:Module_Settings_organization_save"),
            ("Module_Settings_preferences", "GET", "configuration:Module_Settings_preferences"),
            ("Module_Settings_preferences_save", "POST", "configuration:Module_Settings_preferences_save"),
            ("Module_Settings_business_rules", "GET", "configuration:Module_Settings_business_rules"),
            ("Module_Settings_business_rules_save", "POST", "configuration:Module_Settings_business_rules_save"),
            ("Module_Settings_system_logo", "GET", "configuration:Module_Settings_system_logo"),
            ("Module_Settings_organization_logo", "GET", "configuration:Module_Settings_organization_logo"),
        )
        for route_name, method, reverse_name in routes:
            with self.subTest(route=route_name):
                response = getattr(self.client, method.lower())(reverse(reverse_name))
                self.assertEqual(response.status_code, 403)

    def test_settings_mutation_routes_reject_get(self):
        routes = (
            "Module_Settings_system_save",
            "Module_Settings_organization_save",
            "Module_Settings_preferences_save",
            "Module_Settings_business_rules_save",
        )
        self.grant_routes(*routes)
        for route_name in routes:
            with self.subTest(route=route_name):
                response = self.client.get(reverse(f"configuration:{route_name}"))
                self.assertEqual(response.status_code, 405)

    def test_settings_index_lists_only_screens_the_user_can_open(self):
        self.grant_routes("Module_Settings_index", "Module_Settings_system")

        response = self.client.get(reverse("configuration:Module_Settings_index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "System configuration")
        self.assertNotContains(response, "Organization settings")
        self.assertNotContains(response, "User preferences")
        self.assertNotContains(response, "Business rules")

    def test_system_configuration_is_validated_audited_and_effective_immediately(self):
        self.grant_routes("Module_Settings_system", "Module_Settings_system_save")
        response = self.client.post(
            reverse("configuration:Module_Settings_system_save"),
            {
                "application_name": "Updated ERP",
                "currency_code": "USD",
                "currency_symbol": "$",
                "number_format": "western",
                "date_format": "%Y-%m-%d",
                "time_zone": "UTC",
                "fiscal_year_start_month": "1",
                "fiscal_year_start_day": "1",
                "minimum_password_length": "14",
                "session_idle_minutes": "45",
                "upload_limit_mb": "4",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(get_system_configuration().application_name, "Updated ERP")
        self.assertEqual(get_system_configuration().minimum_password_length, 14)
        audit = AuditLog.objects.get(
            entity_name="SystemConfiguration", action="Create"
        )
        self.assertEqual(audit.new_values["application_name"], "Updated ERP")
        self.assertTrue(
            AuditLog.objects.filter(
                entity_name="HTTPMutation",
                action="RequestMutation",
                new_values__route_name="Module_Settings_system_save",
            ).exists()
        )
        response = self.client.post(
            reverse("configuration:Module_Settings_system_save"),
            {
                "application_name": "Updated ERP Two",
                "currency_code": "USD",
                "currency_symbol": "$",
                "number_format": "western",
                "date_format": "%Y-%m-%d",
                "time_zone": "UTC",
                "fiscal_year_start_month": "1",
                "fiscal_year_start_day": "1",
                "minimum_password_length": "14",
                "session_idle_minutes": "45",
                "upload_limit_mb": "4",
            },
        )
        self.assertEqual(response.status_code, 302)
        update = AuditLog.objects.get(
            entity_name="SystemConfiguration", action="Update"
        )
        self.assertEqual(update.old_values["application_name"], "Updated ERP")
        self.assertEqual(update.new_values["application_name"], "Updated ERP Two")

    @override_settings(
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.redis.RedisCache",
                "LOCATION": "redis://127.0.0.1:1/0",
            }
        }
    )
    def test_settings_are_read_from_database_when_shared_cache_is_unavailable(self):
        persisted = SystemConfiguration.objects.create(
            application_name="Database authoritative"
        )

        self.assertEqual(
            get_system_configuration().pk,
            persisted.pk,
        )
        self.assertEqual(
            get_system_configuration().application_name,
            "Database authoritative",
        )

    def test_invalid_system_configuration_does_not_change_persisted_settings(self):
        self.grant_routes("Module_Settings_system", "Module_Settings_system_save")
        response = self.client.post(
            reverse("configuration:Module_Settings_system_save"),
            {
                "application_name": "Invalid ERP",
                "currency_code": "USD",
                "currency_symbol": "$",
                "number_format": "western",
                "date_format": "%Y-%m-%d",
                "time_zone": "Not/A-Timezone",
                "fiscal_year_start_month": "1",
                "fiscal_year_start_day": "1",
                "minimum_password_length": "14",
                "session_idle_minutes": "45",
                "upload_limit_mb": "4",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(SystemConfiguration.objects.exists())

    def test_user_preferences_only_update_the_logged_in_user(self):
        self.grant_routes(
            "Module_Settings_preferences",
            "Module_Settings_preferences_save",
        )
        other_user = get_user_model().objects.create_user(
            username="another-preference-user",
            password="A-strong-test-password-456",
            branch=self.branch,
        )
        response = self.client.post(
            reverse("configuration:Module_Settings_preferences_save"),
            {
                "user": str(other_user.pk),
                "language": "bn",
                "default_page_size": "50",
                "default_landing_page": "/",
                "date_format": "%Y-%m-%d",
            },
        )

        self.assertEqual(response.status_code, 302)
        preference = UserPreference.objects.get(user=self.user)
        self.assertEqual(preference.language, "bn")
        self.assertFalse(UserPreference.objects.filter(user=other_user).exists())
        self.assertTrue(
            AuditLog.objects.filter(
                entity_name="UserPreference",
                entity_id=str(preference.pk),
                action="Create",
            ).exists()
        )

    def test_every_settings_mutation_route_writes_a_request_audit(self):
        routes = (
            "Module_Settings_system_save",
            "Module_Settings_organization_save",
            "Module_Settings_preferences_save",
            "Module_Settings_business_rules_save",
        )
        self.grant_routes(*routes)
        requests = (
            (
                "Module_Settings_system_save",
                {
                    "application_name": "Mutation Audit",
                    "currency_code": "BDT",
                    "currency_symbol": "Tk",
                    "number_format": "western",
                    "date_format": "%d-%b-%Y",
                    "time_zone": "UTC",
                    "fiscal_year_start_month": "1",
                    "fiscal_year_start_day": "1",
                    "minimum_password_length": "12",
                    "session_idle_minutes": "30",
                    "upload_limit_mb": "2",
                },
            ),
            (
                "Module_Settings_organization_save",
                {
                    "legal_name": "Mutation Audit Organization",
                    "registration_number": "REG-1",
                    "address": "Main Street",
                    "phone": "",
                    "email": "",
                    "website": "",
                },
            ),
            (
                "Module_Settings_preferences_save",
                {
                    "language": "en-us",
                    "default_page_size": "25",
                    "default_landing_page": "/",
                    "date_format": "%d-%b-%Y",
                },
            ),
            (
                "Module_Settings_business_rules_save",
                {
                    "rounding_mode": "ROUND_HALF_UP",
                    "repayment_allocation_order": [
                        "penalty", "fees", "interest", "principal"
                    ],
                    "member_status_rules_json": (
                        '{"loan_application":["active"],'
                        '"loan_repayment":["active","inactive","suspended"],'
                        '"savings_deposit":["active","inactive"],'
                        '"savings_withdrawal":["active"]}'
                    ),
                    "collection_rules_json": (
                        '{"allow_advance_collection":true,'
                        '"require_short_collection_reason":true}'
                    ),
                },
            ),
        )
        expected_entities = {
            "Module_Settings_system_save": "SystemConfiguration",
            "Module_Settings_organization_save": "OrganizationConfiguration",
            "Module_Settings_preferences_save": "UserPreference",
            "Module_Settings_business_rules_save": "BusinessRules",
        }

        for route_name, data in requests:
            response = self.client.post(
                reverse(f"configuration:{route_name}"),
                data,
            )
            self.assertEqual(response.status_code, 302, route_name)
            self.assertTrue(
                AuditLog.objects.filter(
                    entity_name="HTTPMutation",
                    action="RequestMutation",
                    new_values__route_name=route_name,
                ).exists(),
                route_name,
            )
            self.assertTrue(
                AuditLog.objects.filter(
                    entity_name=expected_entities[route_name],
                    action="Create",
                ).exists(),
                route_name,
            )

    def test_settings_change_rolls_back_when_its_audit_write_fails(self):
        self.grant_routes("Module_Settings_system", "Module_Settings_system_save")
        data = {
            "application_name": "Must Roll Back",
            "currency_code": "BDT",
            "currency_symbol": "Tk",
            "number_format": "western",
            "date_format": "%d-%b-%Y",
            "time_zone": "UTC",
            "fiscal_year_start_month": "1",
            "fiscal_year_start_day": "1",
            "minimum_password_length": "12",
            "session_idle_minutes": "30",
            "upload_limit_mb": "2",
        }

        with patch(
            "core.configuration.services.log_action",
            side_effect=RuntimeError("audit write unavailable"),
        ), self.assertRaises(RuntimeError):
            self.client.post(
                reverse("configuration:Module_Settings_system_save"),
                data,
            )

        self.assertFalse(SystemConfiguration.objects.exists())

    def test_user_date_and_currency_number_formats_are_applied(self):
        configuration = SystemConfiguration(
            currency_symbol="₹",
            number_format="indian",
            date_format="%d-%b-%Y",
        )
        preference = SimpleNamespace(date_format="%d/%m/%Y")

        self.assertEqual(config_money("12345678.9", configuration), "₹1,23,45,678.90")
        self.assertEqual(user_date(date(2026, 10, 30), preference), "30/10/2026")
