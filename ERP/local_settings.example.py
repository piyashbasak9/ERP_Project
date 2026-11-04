# ruff: noqa: N999
"""
Development-only overrides. Copy to ERP/local_settings.py and edit locally.

This example contains no credentials. Keep database connection values in .env;
the base settings continue to read DB_* values from that file/environment.
The enforced Content Security Policy is intentionally not overridden here.
"""

import os

# Replace this placeholder in your ignored local_settings.py with a generated,
# persistent development-only key. Do not reuse a production key.
SECRET_KEY = "replace-with-a-generated-development-only-secret"
DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1"]
CSRF_TRUSTED_ORIGINS = [
    "http://127.0.0.1:8000",
    "http://localhost:8000",
]

# Local HTTP is permitted only for this development configuration.
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_HSTS_SECONDS = 0

# Prefer plaintext PostgreSQL locally; preserve all DB_* values from .env.
globals()["DATABASES"]["default"]["OPTIONS"] = {"sslmode": "prefer"}

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "erp-local-cache",
    }
}

# Celery tasks run synchronously in development when the project has configured
# a broker or result backend. This does not disable task execution.
CELERY_TASK_ALWAYS_EAGER = bool(
    globals().get("CELERY_BROKER_URL") or globals().get("CELERY_RESULT_BACKEND")
)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "development": {
            "()": "core.common.structured_logging.DevelopmentFormatter",
            "format": "%(asctime)s %(levelname)s %(name)s: %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "level": "DEBUG",
            "formatter": "development",
        },
    },
    "root": {"handlers": ["console"], "level": "DEBUG"},
    "loggers": {
        "django": {"handlers": ["console"], "level": "DEBUG", "propagate": False},
        "ERP": {"handlers": ["console"], "level": "DEBUG", "propagate": False},
        "core": {"handlers": ["console"], "level": "DEBUG", "propagate": False},
        "django.db.backends": {
            "handlers": ["console"],
            "level": "DEBUG" if os.environ.get("LOG_SQL") == "1" else "WARNING",
            "propagate": False,
        },
    },
}
