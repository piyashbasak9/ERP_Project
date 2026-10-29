from django.db import migrations

FORWARD_SQL = """
CREATE FUNCTION savings_reject_posted_transaction_mutation() RETURNS trigger AS $$
BEGIN
    IF OLD.status = 'posted' THEN
        RAISE EXCEPTION 'Posted savings transactions are immutable; create a reversal instead.'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER savings_transactions_posted_immutable
BEFORE UPDATE OR DELETE ON savings_transactions
FOR EACH ROW EXECUTE FUNCTION savings_reject_posted_transaction_mutation();

CREATE FUNCTION savings_reject_posted_journal_mutation() RETURNS trigger AS $$
BEGIN
    IF OLD.status = 'posted' THEN
        RAISE EXCEPTION 'Posted journal entries are immutable; create a reversal instead.'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER accounting_journal_entries_posted_immutable
BEFORE UPDATE OR DELETE ON accounting_journal_entries
FOR EACH ROW EXECUTE FUNCTION savings_reject_posted_journal_mutation();

CREATE FUNCTION savings_reject_posted_journal_line_mutation() RETURNS trigger AS $$
DECLARE
    old_entry_status varchar(24);
    new_entry_status varchar(24);
BEGIN
    IF TG_OP <> 'INSERT' THEN
        SELECT status INTO old_entry_status
        FROM accounting_journal_entries WHERE id = OLD.entry_id;
    END IF;
    IF TG_OP <> 'DELETE' THEN
        SELECT status INTO new_entry_status
        FROM accounting_journal_entries WHERE id = NEW.entry_id;
    END IF;
    IF old_entry_status = 'posted' OR new_entry_status = 'posted' THEN
        RAISE EXCEPTION 'Lines on posted journal entries are immutable.'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER accounting_journal_lines_posted_immutable
BEFORE INSERT OR UPDATE OR DELETE ON accounting_journal_lines
FOR EACH ROW EXECUTE FUNCTION savings_reject_posted_journal_line_mutation();
"""

REVERSE_SQL = """
DROP TRIGGER IF EXISTS accounting_journal_lines_posted_immutable ON accounting_journal_lines;
DROP FUNCTION IF EXISTS savings_reject_posted_journal_line_mutation();
DROP TRIGGER IF EXISTS accounting_journal_entries_posted_immutable ON accounting_journal_entries;
DROP FUNCTION IF EXISTS savings_reject_posted_journal_mutation();
DROP TRIGGER IF EXISTS savings_transactions_posted_immutable ON savings_transactions;
DROP FUNCTION IF EXISTS savings_reject_posted_transaction_mutation();
"""


class Migration(migrations.Migration):

    dependencies = [
        ('accounting', '0004_alter_systemaccountmapping_key'),
        ('savings', '0003_savingsproduct_dormancy_options'),
    ]

    operations = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
    ]
