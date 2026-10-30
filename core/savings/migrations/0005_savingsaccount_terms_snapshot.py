from decimal import Decimal

from django.db import migrations, models


def snapshot_existing_account_terms(apps, schema_editor):
    Account = apps.get_model('savings', 'SavingsAccount')
    names = (
        'code',
        'name',
        'savings_type',
        'annual_interest_rate',
        'interest_method',
        'posting_frequency',
        'minimum_opening_balance',
        'minimum_balance',
        'dormant_after_days',
        'pays_interest_when_dormant',
        'fee_amount',
        'maximum_withdrawal',
        'withdrawal_approval_threshold',
        'withholding_tax_rate',
        'allow_withdrawals',
    )
    for account in Account.objects.select_related('product').iterator():
        account.terms_snapshot = {
            name: (
                str(getattr(account.product, name))
                if isinstance(getattr(account.product, name), Decimal)
                else getattr(account.product, name)
            )
            for name in names
        }
        account.save(update_fields=['terms_snapshot'])


class Migration(migrations.Migration):

    dependencies = [
        ('savings', '0004_posted_financial_record_triggers'),
    ]

    operations = [
        migrations.AddField(
            model_name='savingsaccount',
            name='terms_snapshot',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.RunPython(snapshot_existing_account_terms, migrations.RunPython.noop),
    ]
