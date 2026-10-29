from django.core.management.base import BaseCommand

from core.accounts.permission_utils import sync_permissions


class Command(BaseCommand):
    help = 'Synchronize route-based permissions with the current URL configuration.'

    def handle(self, *args, **options):
        count = sync_permissions()
        self.stdout.write(self.style.SUCCESS(f'Synchronized {count} route permissions.'))
