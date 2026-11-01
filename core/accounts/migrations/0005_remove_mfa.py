from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0004_recoverycode'),
    ]

    operations = [
        migrations.DeleteModel(
            name='RecoveryCode',
        ),
        migrations.RunSQL(
            sql='DROP TABLE IF EXISTS otp_totp_totpdevice CASCADE;',
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
