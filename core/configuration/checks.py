"""Django deploy checks for development settings leaking into production."""

import os

from django.conf import settings
from django.core.checks import Error, register

from .production_guard import (
    get_production_setting_values,
    production_setting_violations,
)


@register(deploy=True)
def production_settings_check(app_configs, **kwargs):
    violations = production_setting_violations(
        get_production_setting_values(settings),
        local_settings_path=settings.BASE_DIR / "ERP" / "local_settings.py",
    )
    if os.environ.get("DJANGO_ENV") != "production":
        violations.append("DJANGO_ENV must be production for deployment checks")
    return [
        Error(message, id="configuration.E001")
        for message in violations
    ]
