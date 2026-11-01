from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django_otp.plugins.otp_totp.models import TOTPDevice

from core.accounts.models import RecoveryCode
from core.audit.models import AuditLog


class Command(BaseCommand):
    help = 'Reset MFA for a user from a trusted server management session.'

    def add_arguments(self, parser):
        parser.add_argument('--username', required=True)
        parser.add_argument('--reason', required=True)
        parser.add_argument('--operator', required=True)

    def handle(self, *args, **options):
        username = options['username'].strip()
        reason = options['reason'].strip()
        operator = options['operator'].strip()
        if not username or not reason or not operator:
            raise CommandError('Username, reason, and operator must not be blank.')
        if len(reason) > 500 or len(operator) > 150:
            raise CommandError('Reason must be at most 500 characters and operator at most 150.')

        User = get_user_model()
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist as exc:
            raise CommandError(f'No user exists with username {username!r}.') from exc

        with transaction.atomic():
            TOTPDevice.objects.filter(user=user).delete()
            RecoveryCode.objects.filter(user=user).delete()
            AuditLog.objects.create(
                user=None,
                user_name=f'server-command:{operator}',
                action='MFAReset',
                entity_name=user._meta.object_name,
                entity_id=str(user.pk),
                new_values={
                    'mfa_enrollment_required': True,
                    'reset_via_server_command': True,
                },
                remarks=reason,
            )
        cache.delete(f'accounts:mfa-failures:{user.pk}')
        self.stdout.write(
            self.style.SUCCESS(
                f'MFA reset for {username}; enrollment is required at next login.'
            )
        )
