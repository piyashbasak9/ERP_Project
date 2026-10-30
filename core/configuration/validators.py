from django.conf import settings
from django.contrib.auth.password_validation import MinimumLengthValidator

from .services import get_system_configuration


class ConfiguredMinimumLengthValidator(MinimumLengthValidator):
    def __init__(self, min_length=None):
        self.min_length = min_length or getattr(
            settings, "PASSWORD_MIN_LENGTH", 12
        )

    def get_help_text(self):
        return (
            f"Your password must contain at least "
            f"{get_system_configuration().minimum_password_length} characters."
        )

    def validate(self, password, user=None):
        self.min_length = get_system_configuration().minimum_password_length
        return super().validate(password, user)
