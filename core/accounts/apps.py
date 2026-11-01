from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core.accounts'

    def ready(self):
        from . import signals  # noqa: F401

    label = 'accounts'
