import io
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest import TestCase

from django.core.exceptions import ImproperlyConfigured

from core.configuration.production_guard import (
    production_setting_violations,
    validate_production_settings,
)
from ERP.local_loader import LOCAL_SETTINGS_NOTICE, load_local_settings


class LocalSettingsLoaderTests(TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.path = Path(self.temporary_directory.name) / "local_settings.py"
        self.path.write_text("DEBUG = True\n", encoding="utf-8")

    def test_production_rejects_an_existing_local_settings_file(self):
        with self.assertRaisesRegex(
            ImproperlyConfigured, "must not be present in production"
        ):
            load_local_settings({}, environment="production", path=self.path)

    def test_production_rejects_a_dangling_local_settings_symlink(self):
        self.path.unlink()
        self.path.symlink_to(self.path.with_name("missing_target.py"))

        with self.assertRaisesRegex(
            ImproperlyConfigured, "must not be present in production"
        ):
            load_local_settings({}, environment="production", path=self.path)

    def test_production_without_a_local_file_loads_nothing(self):
        namespace = {"DEBUG": False}
        self.path.unlink()

        loaded = load_local_settings(
            namespace, environment="production", path=self.path
        )

        self.assertFalse(loaded)
        self.assertEqual(namespace, {"DEBUG": False})

    def test_test_environment_ignores_local_settings(self):
        namespace = {"DEBUG": False}
        output = io.StringIO()

        with redirect_stdout(output):
            loaded = load_local_settings(
                namespace, environment="test", path=self.path
            )

        self.assertFalse(loaded)
        self.assertEqual(namespace, {"DEBUG": False})
        self.assertEqual(output.getvalue(), "")

    def test_local_environment_loads_settings_and_prints_notice(self):
        namespace = {"DEBUG": False}
        output = io.StringIO()

        with redirect_stdout(output):
            loaded = load_local_settings(
                namespace, environment="local", path=self.path
            )

        self.assertTrue(loaded)
        self.assertTrue(namespace["DEBUG"])
        self.assertEqual(output.getvalue().strip(), LOCAL_SETTINGS_NOTICE)

    def test_missing_local_file_does_not_change_settings(self):
        namespace = {"DEBUG": False, "ALLOWED_HOSTS": ["example.test"]}
        self.path.unlink()
        output = io.StringIO()

        with redirect_stdout(output):
            loaded = load_local_settings(
                namespace, environment="local", path=self.path
            )

        self.assertFalse(loaded)
        self.assertEqual(
            namespace, {"DEBUG": False, "ALLOWED_HOSTS": ["example.test"]}
        )
        self.assertEqual(output.getvalue(), "")


class ProductionSettingsGuardTests(TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.local_path = Path(self.temporary_directory.name) / "local_settings.py"
        self.safe_values = {
            "DEBUG": False,
            "SECRET_KEY": "s" * 64,
            "SECURE_SSL_REDIRECT": True,
            "SECURE_HSTS_SECONDS": 31_536_000,
            "SESSION_COOKIE_SECURE": True,
            "CSRF_COOKIE_SECURE": True,
            "EMAIL_BACKEND": "django.core.mail.backends.smtp.EmailBackend",
            "CELERY_TASK_ALWAYS_EAGER": False,
            "ALLOWED_HOSTS": ["erp.example.test"],
            "AXES_FAILURE_LIMIT": 5,
            "AXES_ENABLED": True,
            "MFA_ENFORCEMENT_ENABLED": True,
            "DATABASES": {
                "default": {"OPTIONS": {"sslmode": "verify-full"}}
            },
            "CSRF_TRUSTED_ORIGINS": ["https://erp.example.test"],
        }

    def test_production_guard_accepts_only_safe_values_without_local_file(self):
        validate_production_settings(
            self.safe_values, local_settings_path=self.local_path
        )

    def test_production_guard_rejects_each_development_value(self):
        unsafe_values = (
            ("DEBUG", True),
            ("SECRET_KEY", "short"),
            ("SECURE_SSL_REDIRECT", False),
            ("SECURE_HSTS_SECONDS", 0),
            ("SESSION_COOKIE_SECURE", False),
            ("CSRF_COOKIE_SECURE", False),
            (
                "EMAIL_BACKEND",
                "django.core.mail.backends.console.EmailBackend",
            ),
            ("CELERY_TASK_ALWAYS_EAGER", True),
            ("ALLOWED_HOSTS", ["*"]),
            ("AXES_FAILURE_LIMIT", 0),
            ("AXES_ENABLED", False),
            ("MFA_ENFORCEMENT_ENABLED", False),
            (
                "DATABASES",
                {"default": {"OPTIONS": {"sslmode": "prefer"}}},
            ),
            ("CSRF_TRUSTED_ORIGINS", ["http://localhost:8000"]),
        )
        for setting_name, unsafe_value in unsafe_values:
            with self.subTest(setting=setting_name):
                values = self.safe_values | {setting_name: unsafe_value}
                with self.assertRaises(ImproperlyConfigured):
                    validate_production_settings(
                        values, local_settings_path=self.local_path
                    )

    def test_production_guard_rejects_a_local_settings_file(self):
        self.local_path.touch()

        violations = production_setting_violations(
            self.safe_values, local_settings_path=self.local_path
        )

        self.assertIn("ERP/local_settings.py must not be present", violations)

    def test_production_guard_rejects_a_dangling_local_settings_symlink(self):
        self.local_path.symlink_to(self.local_path.with_name("missing_target.py"))

        violations = production_setting_violations(
            self.safe_values, local_settings_path=self.local_path
        )

        self.assertIn("ERP/local_settings.py must not be present", violations)

    def test_production_guard_rejects_missing_mfa_enforcement(self):
        values = self.safe_values | {"MFA_ENFORCEMENT_ENABLED": False}

        with self.assertRaisesRegex(
            ImproperlyConfigured, "MFA enforcement is unavailable or disabled"
        ):
            validate_production_settings(values, local_settings_path=self.local_path)
