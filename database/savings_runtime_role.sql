-- Run as the table owner or a database administrator after migrations.
-- The runtime role must not own these tables, inherit a broader writer role, or
-- be a superuser; PostgreSQL owners and superusers can bypass these grants.

REVOKE UPDATE, DELETE ON TABLE savings_transactions FROM erp_runtime;
REVOKE UPDATE (
    id, branch_id, account_id, transaction_type, status, transaction_date, amount,
    gross_amount, tax_amount, period_start, period_end, balance_before, balance_after,
    payment_channel, contribution_member_id, journal_entry_id, reversal_of_id,
    idempotency_key, narration, created_by_id, approved_by_id, rejected_by_id,
    rejection_reason, created_at
) ON TABLE savings_transactions FROM erp_runtime;
GRANT UPDATE (
    status,
    balance_before,
    balance_after,
    journal_entry_id,
    approved_by_id,
    rejected_by_id,
    rejection_reason
) ON TABLE savings_transactions TO erp_runtime;

REVOKE UPDATE, DELETE ON TABLE accounting_journal_entries FROM erp_runtime;
REVOKE UPDATE (
    id, branch_id, fiscal_year_id, period_id, voucher_type, voucher_number,
    journal_date, narration, idempotency_key, source_type, source_id, status,
    requires_approval, created_by_id, posted_by_id, posted_at, reversal_of_id
) ON TABLE accounting_journal_entries FROM erp_runtime;
GRANT UPDATE (status, posted_by_id, posted_at)
    ON TABLE accounting_journal_entries TO erp_runtime;

REVOKE UPDATE, DELETE ON TABLE accounting_journal_lines FROM erp_runtime;
REVOKE UPDATE (id, entry_id, account_id, debit, credit, narration)
    ON TABLE accounting_journal_lines FROM erp_runtime;

GRANT SELECT, INSERT, UPDATE ON TABLE loan_products TO erp_runtime;
GRANT SELECT, INSERT ON TABLE
    loan_applications, loans, loan_installments, loan_payments,
    loan_penalties, loan_recoveries TO erp_runtime;
GRANT SELECT, INSERT ON TABLE
    loan_guarantors, loan_collateral, loan_status_history,
    loan_reschedules TO erp_runtime;
GRANT SELECT, INSERT, UPDATE ON TABLE
    loan_approval_tiers, loan_par_buckets TO erp_runtime;
REVOKE UPDATE, DELETE ON TABLE
    loan_guarantors, loan_collateral, loan_status_history,
    loan_reschedules FROM erp_runtime;
REVOKE DELETE ON TABLE
    loan_approval_tiers, loan_par_buckets FROM erp_runtime;

REVOKE UPDATE, DELETE ON TABLE loan_applications FROM erp_runtime;
GRANT UPDATE (
    status, approved_amount, reviewed_by_id, review_comment,
    submitted_at, reviewed_at, updated_at
) ON TABLE loan_applications TO erp_runtime;

REVOKE UPDATE, DELETE ON TABLE loans FROM erp_runtime;
GRANT UPDATE (
    outstanding_principal, written_off_amount, recovered_amount, status,
    schedule_version, effective_annual_rate, accrued_penalty, closed_at,
    write_off_idempotency_key, write_off_reason
) ON TABLE loans TO erp_runtime;

REVOKE UPDATE, DELETE ON TABLE loan_installments FROM erp_runtime;
GRANT UPDATE (
    fee_due, principal_paid, interest_paid, interest_waived, fee_paid
) ON TABLE loan_installments TO erp_runtime;

REVOKE UPDATE, DELETE ON TABLE loan_payments FROM erp_runtime;
REVOKE UPDATE, DELETE ON TABLE loan_recoveries FROM erp_runtime;

REVOKE UPDATE, DELETE ON TABLE loan_penalties FROM erp_runtime;
GRANT UPDATE (amount, paid) ON TABLE loan_penalties TO erp_runtime;

GRANT SELECT, INSERT ON TABLE collection_sheets TO erp_runtime;
REVOKE UPDATE, DELETE ON TABLE collection_sheets FROM erp_runtime;
GRANT UPDATE (
    status, submitted_at, submitted_by_id, cash_received, cash_shortage,
    cash_excess, reconciled_by_id, reconciled_at, variance_journal_id,
    posting_key, posted_by_id, posted_at, cancellation_reason, version
) ON TABLE collection_sheets TO erp_runtime;

GRANT SELECT, INSERT ON TABLE collection_sheet_items TO erp_runtime;
REVOKE UPDATE, DELETE ON TABLE collection_sheet_items FROM erp_runtime;
GRANT UPDATE (
    collected_amount, savings_amount, reason, updated_by_id, updated_at, version
) ON TABLE collection_sheet_items TO erp_runtime;

GRANT SELECT, INSERT ON TABLE collection_postings TO erp_runtime;
REVOKE UPDATE, DELETE ON TABLE collection_postings FROM erp_runtime;

GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO erp_runtime;
