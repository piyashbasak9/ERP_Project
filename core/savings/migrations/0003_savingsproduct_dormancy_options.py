from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ('savings', '0002_savingsaccount_savings_account_balance_nonnegative_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='savingsproduct',
            name='dormant_after_days',
            field=models.PositiveIntegerField(
                blank=True,
                help_text='Days without a posted savings transaction before an account becomes dormant.',
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='savingsproduct',
            name='pays_interest_when_dormant',
            field=models.BooleanField(default=False),
        ),
        migrations.AddConstraint(
            model_name='savingsproduct',
            constraint=models.CheckConstraint(
                condition=Q(dormant_after_days__isnull=True) | Q(dormant_after_days__gte=1),
                name='savings_dormancy_days_positive',
            ),
        ),
    ]
