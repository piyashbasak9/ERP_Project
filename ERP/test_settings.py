"""Test-only settings for Django and pytest."""

import os

from .settings import *

SECURE_SSL_REDIRECT = False

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("TEST_DB_NAME", "erp_test"),
        "USER": os.environ.get("TEST_DB_USER", "erp_test_runner"),
        "PASSWORD": os.environ["TEST_DB_PASSWORD"],
        "HOST": os.environ.get("TEST_DB_HOST", "localhost"),
        "PORT": os.environ.get("TEST_DB_PORT", "5432"),
        "CONN_MAX_AGE": 0,
    }
}

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
