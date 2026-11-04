"""Fail-closed checks for settings that are unsafe in production."""

from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

PRODUCTION_SETTING_NAMES = (
    "DEBUG",
    "SECRET_KEY",
    "SECURE_SSL_REDIRECT",
    "SECURE_HSTS_SECONDS",
    "SESSION_COOKIE_SECURE",
    "CSRF_COOKIE_SECURE",
    "EMAIL_BACKEND",
    "CELERY_TASK_ALWAYS_EAGER",
    "ALLOWED_HOSTS",
    "AXES_FAILURE_LIMIT",
    "AXES_ENABLED",
    "MFA_ENFORCEMENT_ENABLED",
    "DATABASES",
    "CSRF_TRUSTED_ORIGINS",
)


def get_production_setting_values(settings_object):
    return {
        name: getattr(settings_object, name, None)
        for name in PRODUCTION_SETTING_NAMES
    }


def production_setting_violations(values, *, local_settings_path):
    violations = []
    if values.get("DEBUG") is True:
        violations.append("DEBUG must be False")
    if len(values.get("SECRET_KEY", "")) < 50:
        violations.append("SECRET_KEY must be a strong production key")
    if values.get("SECURE_SSL_REDIRECT") is not True:
        violations.append("SECURE_SSL_REDIRECT must be True")
    if int(values.get("SECURE_HSTS_SECONDS", 0)) <= 0:
        violations.append("SECURE_HSTS_SECONDS must be positive")
    if values.get("SESSION_COOKIE_SECURE") is not True:
        violations.append("SESSION_COOKIE_SECURE must be True")
    if values.get("CSRF_COOKIE_SECURE") is not True:
        violations.append("CSRF_COOKIE_SECURE must be True")
    if values.get("EMAIL_BACKEND") == "django.core.mail.backends.console.EmailBackend":
        violations.append("the console email backend is development-only")
    if values.get("CELERY_TASK_ALWAYS_EAGER") is True:
        violations.append("Celery eager mode must be disabled")
    if "*" in values.get("ALLOWED_HOSTS", ()):
        violations.append("ALLOWED_HOSTS must not contain a wildcard")
    if any(
        origin.lower().startswith("http://")
        for origin in values.get("CSRF_TRUSTED_ORIGINS", ())
    ):
        violations.append("CSRF_TRUSTED_ORIGINS must use HTTPS")
    database_options = (
        values.get("DATABASES", {})
        .get("default", {})
        .get("OPTIONS", {})
    )
    if database_options.get("sslmode") not in {
        "require",
        "verify-ca",
        "verify-full",
    }:
        violations.append("PostgreSQL sslmode must require TLS")
    if int(values.get("AXES_FAILURE_LIMIT", 0)) <= 0 or values.get(
        "AXES_ENABLED", True
    ) is False:
        violations.append("login lockout enforcement must be enabled")
    if values.get("MFA_ENFORCEMENT_ENABLED") is not True:
        violations.append(
            "MFA enforcement is unavailable or disabled; production is blocked"
        )
    local_settings = Path(local_settings_path)
    if local_settings.exists() or local_settings.is_symlink():
        violations.append("ERP/local_settings.py must not be present")
    return violations


def validate_production_settings(values, *, local_settings_path):
    violations = production_setting_violations(
        values,
        local_settings_path=local_settings_path,
    )
    if violations:
        raise ImproperlyConfigured(
            "Unsafe production settings: " + "; ".join(violations)
        )
