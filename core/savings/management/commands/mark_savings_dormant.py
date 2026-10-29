from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.test import RequestFactory
from django.utils import timezone
from django.utils.dateparse import parse_date

from core.audit.context import audit_context_var, build_audit_context
from core.savings.services import SavingsService


class Command(BaseCommand):
    help = 'Mark savings accounts dormant after their product-configured inactivity period.'

    def add_arguments(self, parser):
        parser.add_argument('--actor', required=True, help='Active username authorized for every target branch.')
        parser.add_argument('--as-of-date', help='Business date in YYYY-MM-DD format; defaults to today.')

    def handle(self, *args, **options):
        actor = get_user_model().objects.filter(username=options['actor'], is_active=True).first()
        if actor is None:
            raise CommandError('The selected actor does not exist or is inactive.')
        as_of_date = parse_date(options['as_of_date']) if options['as_of_date'] else timezone.localdate()
        if as_of_date is None:
            raise CommandError('--as-of-date must use YYYY-MM-DD format.')

        request = RequestFactory().post('/management/mark-savings-dormant/')
        request.user = actor
        request.active_branch_id = None
        request.META = {'REMOTE_ADDR': 'management-command', 'HTTP_USER_AGENT': 'Django management command'}
        audit_token = audit_context_var.set(build_audit_context(request))
        try:
            changed = SavingsService(request).mark_dormant_accounts(as_of_date=as_of_date)
        finally:
            audit_context_var.reset(audit_token)

        self.stdout.write(self.style.SUCCESS(
            f'Marked {len(changed)} savings account(s) dormant as of {as_of_date}.'
        ))
