from django.db import migrations

FORWARD_SQL = """
DROP TRIGGER IF EXISTS collection_sheet_immutable ON collection_sheets;
DROP FUNCTION IF EXISTS protect_posted_collection_sheet();

CREATE FUNCTION protect_posted_collection_sheet() RETURNS trigger AS $$
BEGIN
    IF OLD.status = 'reversed' THEN
        RAISE EXCEPTION 'Reversed collection sheets are immutable';
    END IF;
    IF OLD.status = 'posted' THEN
        IF TG_OP <> 'UPDATE'
           OR NEW.status <> 'reversed'
           OR (to_jsonb(NEW) - 'status') IS DISTINCT FROM (to_jsonb(OLD) - 'status') THEN
            RAISE EXCEPTION 'Posted collection sheets may only transition to reversed';
        END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'UPDATE' AND NEW.status <> OLD.status THEN
        IF NOT (
            (OLD.status = 'generated' AND NEW.status IN ('in_progress', 'cancelled'))
            OR (OLD.status = 'in_progress' AND NEW.status IN ('submitted', 'cancelled'))
            OR (OLD.status = 'submitted' AND NEW.status = 'reconciled')
            OR (OLD.status = 'reconciled' AND NEW.status = 'posted')
        ) THEN
            RAISE EXCEPTION 'Invalid collection sheet status transition';
        END IF;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER collection_sheet_immutable
BEFORE UPDATE OR DELETE ON collection_sheets
FOR EACH ROW EXECUTE FUNCTION protect_posted_collection_sheet();

CREATE OR REPLACE FUNCTION protect_posted_collection_item() RETURNS trigger AS $$
DECLARE
    parent_status varchar(16);
BEGIN
    SELECT status INTO parent_status
    FROM collection_sheets
    WHERE id = OLD.sheet_id;
    IF parent_status IN ('posted', 'reversed') THEN
        RAISE EXCEPTION 'Rows on posted or reversed collection sheets are immutable';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE FUNCTION protect_collection_reversal_record() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'Collection reversal records are immutable';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER collection_sheet_reversal_immutable
BEFORE UPDATE OR DELETE ON collection_sheet_reversals
FOR EACH ROW EXECUTE FUNCTION protect_collection_reversal_record();

CREATE TRIGGER collection_sheet_reversal_approval_immutable
BEFORE UPDATE OR DELETE ON collection_sheet_reversal_approvals
FOR EACH ROW EXECUTE FUNCTION protect_collection_reversal_record();

CREATE TRIGGER collection_posting_reversal_immutable
BEFORE UPDATE OR DELETE ON collection_posting_reversals
FOR EACH ROW EXECUTE FUNCTION protect_collection_reversal_record();
"""

REVERSE_SQL = """
DROP TRIGGER IF EXISTS collection_posting_reversal_immutable ON collection_posting_reversals;
DROP TRIGGER IF EXISTS collection_sheet_reversal_approval_immutable ON collection_sheet_reversal_approvals;
DROP TRIGGER IF EXISTS collection_sheet_reversal_immutable ON collection_sheet_reversals;
DROP FUNCTION IF EXISTS protect_collection_reversal_record();
DROP TRIGGER IF EXISTS collection_item_immutable ON collection_sheet_items;
CREATE OR REPLACE FUNCTION protect_posted_collection_item() RETURNS trigger AS $$
DECLARE
    parent_status varchar(16);
BEGIN
    SELECT status INTO parent_status FROM collection_sheets WHERE id = OLD.sheet_id;
    IF parent_status = 'posted' THEN
        RAISE EXCEPTION 'Rows on posted collection sheets are immutable';
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER collection_item_immutable
BEFORE UPDATE OR DELETE ON collection_sheet_items
FOR EACH ROW EXECUTE FUNCTION protect_posted_collection_item();

DROP TRIGGER IF EXISTS collection_sheet_immutable ON collection_sheets;
DROP FUNCTION IF EXISTS protect_posted_collection_sheet();
CREATE FUNCTION protect_posted_collection_sheet() RETURNS trigger AS $$
BEGIN
    IF OLD.status = 'posted' THEN
        RAISE EXCEPTION 'Posted collection sheets are immutable';
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER collection_sheet_immutable
BEFORE UPDATE OR DELETE ON collection_sheets
FOR EACH ROW EXECUTE FUNCTION protect_posted_collection_sheet();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("collections", "0006_remove_collectionsheetreversal_approved_by_and_more"),
    ]

    operations = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
