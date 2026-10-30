from django.db import migrations

FORWARD_SQL = """
CREATE FUNCTION protect_loan_payment_reversal() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'Loan payment reversal records are immutable';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER loan_payment_reversal_immutable
BEFORE UPDATE OR DELETE ON loan_payment_reversals
FOR EACH ROW EXECUTE FUNCTION protect_loan_payment_reversal();
"""

REVERSE_SQL = """
DROP TRIGGER IF EXISTS loan_payment_reversal_immutable ON loan_payment_reversals;
DROP FUNCTION IF EXISTS protect_loan_payment_reversal();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("loans", "0007_loanpayment_allocation_snapshot_loanpaymentreversal"),
    ]

    operations = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
