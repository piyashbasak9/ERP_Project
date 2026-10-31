"""Test-only settings for Django and pytest."""

import os

from django.core.exceptions import ImproperlyConfigured

os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from .settings import *

SECURE_SSL_REDIRECT = False

REQUIRED_TEST_DATABASE_VARIABLES = (
    "TEST_DB_NAME",
    "TEST_DB_USER",
    "TEST_DB_PASSWORD",
)
missing_test_database_variables = [
    variable
    for variable in REQUIRED_TEST_DATABASE_VARIABLES
    if not os.environ.get(variable)
]
if missing_test_database_variables:
    raise ImproperlyConfigured(
        "Missing required PostgreSQL test database environment variable(s): "
        + ", ".join(missing_test_database_variables)
    )

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ["TEST_DB_NAME"],
        "USER": os.environ["TEST_DB_USER"],
        "PASSWORD": os.environ["TEST_DB_PASSWORD"],
        "HOST": os.environ.get("TEST_DB_HOST", "localhost"),
        "PORT": os.environ.get("TEST_DB_PORT", "5432"),
        "CONN_MAX_AGE": 0,
    }
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "erp-test-cache",
    }
}

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
