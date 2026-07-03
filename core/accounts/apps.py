import os

from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core.accounts'
    label = 'accounts'

    def ready(self):
        # Avoid running twice under Django's autoreloader.
        if os.environ.get('RUN_MAIN') == 'true':
            pass
        elif os.environ.get('RUN_MAIN') is None and os.environ.get('WERKZEUG_RUN_MAIN') is None:
            pass

        try:
            from .permission_utils import sync_permission_route_names

            print('[accounts] starting permission route_name sync')
            updated = sync_permission_route_names()
            print(f"[accounts] permission route_name sync finished; updated={updated}")
        except Exception as e:
            print(f"[accounts] Error occurred while syncing permission route_name values: {e}")
