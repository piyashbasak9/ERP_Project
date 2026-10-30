from django.apps import AppConfig


class AuditConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core.audit'
    label = 'audit'

    def ready(self):
        from . import signals

        signals.register()
