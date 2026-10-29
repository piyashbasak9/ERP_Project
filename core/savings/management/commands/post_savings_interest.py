import uuid
from calendar import monthrange
from datetime import date

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.test import RequestFactory
from django.utils.dateparse import parse_date

from core.audit.context import audit_context_var, build_audit_context
from core.savings.models import SavingsAccount, SavingsProduct
from core.savings.services import SavingsService


class Command(BaseCommand):
    help = 'Post savings interest for a complete product posting period.'

    def add_arguments(self, parser):
        parser.add_argument('--actor', required=True, help='Active username authorized for every target branch.')
        period = parser.add_mutually_exclusive_group(required=True)
        period.add_argument('--as-of-date', help='Post the due calendar period ending on this date.')
        period.add_argument('--start-date', help='Manual period start in YYYY-MM-DD format.')
        parser.add_argument('--end-date', help='Manual period end in YYYY-MM-DD format.')

    def handle(self, *args, **options):
        actor = get_user_model().objects.filter(
            username=options['actor'],
            is_active=True,
        ).first()
        if actor is None:
            raise CommandError('The selected actor does not exist or is inactive.')

        if options['as_of_date']:
            as_of_date = parse_date(options['as_of_date'])
            if as_of_date is None:
                raise CommandError('--as-of-date must use YYYY-MM-DD format.')
            period_dates = self._due_periods(as_of_date)
        else:
            start_date = parse_date(options['start_date'])
            end_date = parse_date(options['end_date'])
            if start_date is None or end_date is None:
                raise CommandError('Both dates must use YYYY-MM-DD format.')
            if end_date < start_date:
                raise CommandError('The end date must not precede its start date.')
            period_dates = [(start_date, end_date)]
            if not options['end_date']:
                raise CommandError('--end-date is required with --start-date.')

        request = RequestFactory().post('/management/post-savings-interest/')
        request.user = actor
        request.active_branch_id = None
        request.META = {'REMOTE_ADDR': 'management-command', 'HTTP_USER_AGENT': 'Django management command'}
        audit_token = audit_context_var.set(build_audit_context(request))
        account_ids = SavingsAccount.unscoped.filter(
            branch_id__in=actor.accessible_branch_ids(),
            status__in=[SavingsAccount.STATUS_ACTIVE, SavingsAccount.STATUS_DORMANT],
        ).values_list(
            'pk',
            'account_number',
            'product__posting_frequency',
        )
        service = SavingsService(request)
        successes = []
        failures = []
        skipped = []
        try:
            for account_id, account_number, frequency in account_ids.iterator():
                for start_date, end_date in (
                    period_dates.get(frequency, []) if options['as_of_date'] else period_dates
                ):
                    idempotency_key = uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f'savings-interest:{account_id}:{start_date.isoformat()}:{end_date.isoformat()}',
                    )
                    try:
                        gross_interest = service.calculate_interest(
                            account_id=account_id,
                            start_date=start_date,
                            end_date=end_date,
                        )
                        if gross_interest <= 0:
                            skipped.append(f'{account_number}: no positive interest accrued for {start_date}')
                            continue
                        result = service.post_interest(
                            account_id=account_id,
                            start_date=start_date,
                            end_date=end_date,
                            idempotency_key=idempotency_key,
                        )
                    except ValidationError as exc:
                        failures.append(f'{account_number}: {"; ".join(exc.messages)}')
                    else:
                        successes.append(f'{account_number}: {result.amount}')
        finally:
            audit_context_var.reset(audit_token)

        for success in successes:
            self.stdout.write(self.style.SUCCESS(success))
        for item in skipped:
            self.stdout.write(self.style.WARNING(item))
        for failure in failures:
            self.stderr.write(self.style.ERROR(failure))
        if failures:
            raise CommandError(
                f'Interest posting completed with {len(failures)} failure(s) and '
                f'{len(successes)} successful or idempotently completed account(s); '
                f'{len(skipped)} account-period(s) skipped.'
            )
        self.stdout.write(self.style.SUCCESS(
            f'Interest posting completed: {len(successes)} account-period(s) posted or already posted; '
            f'{len(skipped)} skipped.'
        ))

    @staticmethod
    def _due_periods(as_of_date):
        periods = {
            SavingsProduct.FREQUENCY_MONTHLY: [],
            SavingsProduct.FREQUENCY_QUARTERLY: [],
            SavingsProduct.FREQUENCY_HALF_YEARLY: [],
            SavingsProduct.FREQUENCY_YEARLY: [],
        }
        monthly_end = monthrange(as_of_date.year, as_of_date.month)[1]
        if as_of_date.day == monthly_end:
            periods[SavingsProduct.FREQUENCY_MONTHLY].append((as_of_date.replace(day=1), as_of_date))
        if as_of_date.month in {3, 6, 9, 12} and as_of_date.day == monthrange(as_of_date.year, as_of_date.month)[1]:
            quarter_start_month = ((as_of_date.month - 1) // 3) * 3 + 1
            periods[SavingsProduct.FREQUENCY_QUARTERLY].append(
                (date(as_of_date.year, quarter_start_month, 1), as_of_date)
            )
        if as_of_date.month in {6, 12} and as_of_date.day == monthrange(as_of_date.year, as_of_date.month)[1]:
            periods[SavingsProduct.FREQUENCY_HALF_YEARLY].append(
                (date(as_of_date.year, 1 if as_of_date.month == 6 else 7, 1), as_of_date)
            )
        if as_of_date.month == 12 and as_of_date.day == 31:
            periods[SavingsProduct.FREQUENCY_YEARLY].append((date(as_of_date.year, 1, 1), as_of_date))
        return periods
