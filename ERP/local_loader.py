"""Load ignored development-only settings without affecting tests or production."""

import importlib.util
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

LOCAL_SETTINGS_NOTICE = "LOCAL SETTINGS LOADED (development only)"


def load_local_settings(settings_namespace, *, environment=None, path=None):
    settings_path = Path(path) if path is not None else Path(__file__).with_name(
        "local_settings.py"
    )
    current_environment = (
        environment or os.environ.get("DJANGO_ENV") or "local"
    ).strip().lower()

    if current_environment == "production":
        if settings_path.exists() or settings_path.is_symlink():
            raise ImproperlyConfigured(
                "ERP/local_settings.py must not be present in production."
            )
        return False
    if current_environment == "test":
        return False
    if current_environment != "local":
        raise ImproperlyConfigured(
            "DJANGO_ENV must be 'local', 'test', or 'production'."
        )
    if not settings_path.is_file():
        return False

    spec = importlib.util.spec_from_file_location(
        "erp_local_settings", settings_path
    )
    if spec is None or spec.loader is None:
        raise ImproperlyConfigured(
            f"Unable to load local settings from {settings_path}."
        )
    local_module = importlib.util.module_from_spec(spec)
    local_module.__dict__.update(
        (name, value)
        for name, value in settings_namespace.items()
        if name.isupper()
    )
    spec.loader.exec_module(local_module)
    settings_namespace.update(
        (name, value)
        for name, value in vars(local_module).items()
        if name.isupper()
    )
    print(LOCAL_SETTINGS_NOTICE)
    return True
