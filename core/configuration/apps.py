import os
from pathlib import Path

from django.apps import AppConfig
from django.conf import settings

from .production_guard import (
    get_production_setting_values,
    validate_production_settings,
)


class ConfigurationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core.configuration"
    label = "configuration"

    def ready(self):
        from . import checks  # noqa: F401

        if os.environ.get("DJANGO_ENV") == "production":
            validate_production_settings(
                get_production_setting_values(settings),
                local_settings_path=Path(settings.BASE_DIR)
                / "ERP"
                / "local_settings.py",
            )
