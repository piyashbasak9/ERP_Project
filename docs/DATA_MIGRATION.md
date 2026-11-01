# Data Migration Guide

Use this runbook to move spreadsheet or legacy-system data into ERP templates.
Perform a rehearsal with masked/synthetic data first. Use a named maker and a
different checker; never import into production until the opening totals and
rollback plan are approved.

## 1. Prepare and protect the source

1. Name a business owner and a data owner for each source workbook.
2. Freeze or timestamp each source extract. Keep an unmodified, access-controlled
   copy and record its export time, row count and SHA-256 hash.
3. Remove duplicate records, formulas, merged headers, hidden rows, test data,
   unsupported dates and invalid references. Keep identifiers as text so
   leading zeroes are not lost.
4. Agree a single cut-over date and business date. Convert dates to ISO
   `YYYY-MM-DD`; convert monetary values to decimal amounts with at most two
   decimal places. Do not use spreadsheet formula cells as values.
5. Reconcile source counts and totals before converting the sheets. Protect
   national identifiers and personal data during transfer; do not send them in
   email or chat.

## 2. Configure the destination first

Before importing financial rows, create and verify:

1. Branches, hierarchy, centers and groups. Confirm every member/loan maps to
   the intended branch.
2. Named users, roles and branch grants for the maker and checker.
3. Savings and loan products with matching codes and valid terms.
4. Fiscal year and open accounting period covering the opening date.
5. Active postable chart-of-account entries and system mappings. Loan opening
   imports require **Loans to Members** (asset) and **Opening Balance Equity**
   (equity). Configure savings and cash mappings before savings imports.
6. A verified backup and a tested restore path for the destination database and
   private media.

## 3. Convert source sheets in dependency order

### A. Members

Open **Bulk import** at `/imports/`, then download the **Members** template
(`/imports/template/members/`). Supply the
template columns exactly: `member_code`, `first_name`, `last_name`, `phone`,
`email`, `date_of_birth`, and `admission_date`. Member codes must be unique.
Import members before opening accounts, applications or loans. Add optional
member profile and KYC details through the member screens where they are not
part of this template.

**After import:** compare imported member count by branch with the source,
check duplicate codes and required identity/contact fields, and inspect a
sample of member details and KYC status.

### B. Savings accounts and opening balances

Create savings products and accounts through **Savings → Products** and
**Savings → Accounts** first. In **Bulk import** (`/imports/`), download the
**Savings opening balances** template
(`/imports/template/savings_opening/`): `account_number`, `amount`,
`transaction_date`.

The opening transaction posts through the configured savings/cash ledger path
and requires a different checker.

**After import:** compare account counts and balances by branch/product; compare
the sum of account subledgers with the member-savings control account and the
opening journals. Investigate every variance before continuing.

### C. General-ledger opening balances

In **Bulk import** (`/imports/`), download the **GL opening balances** template
(`/imports/template/gl_opening/`): `account_code`, `debit`, `credit`,
`journal_date`, `narration`. Use one journal date for all rows, one positive
side per row, and ensure the import's total debit equals total credit.

Do not include loan receivables or member savings a second time if the savings
or loan opening imports will post those control-account balances. Coordinate
the journal so each opening balance is represented exactly once.

**After import:** compare each account's opening balance with the approved
source trial balance; run the trial balance and confirm total debits equal total
credits.

### D. Existing active loans

In **Bulk import** (`/imports/`), download the **Loan opening balances**
template (`/imports/template/loan_opening/`). The exact columns are:

`member_code`, `product_code`, `disbursed_amount`, `disbursed_date`, `term`,
`frequency`, `outstanding_principal`, `accrued_unpaid_interest`,
`overdue_installments`, `unpaid_penalties`, `last_payment_date`, `opening_date`,
`next_due_date`.

- `term` is the number of remaining installments, not the original term.
- `next_due_date` anchors the generated remaining schedule; the provided
  `overdue_installments` must equal the number of generated installment dates
  strictly before `opening_date`.
- `last_payment_date` may be blank only if the loan has no recorded payment.
  When supplied it must fall between disbursement and opening dates.
- The opening journal posts **outstanding principal only**: debit Loans to
  Members and credit Opening Balance Equity. Accrued interest and unpaid
  penalties are carried as separate loan-subledger dues and are not recognized
  as opening income by this import.
- One member/product pair may occur once in a workbook and cannot already have
  an active loan for that product in the selected branch.

Upload the `.xlsx`, run **Dry-run validate**, download and review the error
report if needed, then select **Confirm**. A different checker must inspect the
source/hash, branch, row count, opening date, totals and error-free validation
before approving. The file hash prevents resubmitting the same workbook as a
new batch.

**After import:** verify the loan count and each loan's schedule, overdue
installments, PAR and penalty balance. Reconcile the sum of outstanding
principal by branch to the Loans to Members ledger balance. Reconcile accrued
interest and penalties separately to the loan statements/subledger; do not
force them into opening equity or income.

## 4. Reconciliation gates

Do not proceed to the next import or cut-over until the relevant owner signs
these checks:

| Gate | Required comparison | Result |
|---|---|---|
| Member master | Source count by branch/status vs ERP; duplicate codes and missing required data | Pass / Fail |
| Savings | Source account count and total balance vs ERP accounts and member-savings control account | Pass / Fail |
| Loans | Source active-loan count, disbursed principal, outstanding principal, accrued interest, overdue count and penalties vs ERP loans/schedules | Pass / Fail |
| General ledger | Source trial balance by account vs ERP trial balance; debits equal credits | Pass / Fail |
| Cross-ledger | Savings and loan subledgers vs their mapped GL control balances; cash/opening equity reviewed | Pass / Fail |
| Branch isolation | Sample each branch and confirm records, reports and users cannot see another branch without an approved grant | Pass / Fail |

Record source amount, ERP amount, variance, explanation, reviewer and date. A
variance is not accepted solely because the overall journal balances.

## 5. Cut-over

1. Announce a transaction freeze and stop edits in the source system.
2. Take and verify a final source extract and record its hash, timestamp, row
   counts and totals.
3. Take a destination backup of PostgreSQL and private media. Verify it can be
   restored before importing.
4. Run the approved import sequence in the destination using distinct maker and
   checker accounts. Retain the batch IDs and validation/error reports.
5. Run all reconciliation gates, report checks and UAT cases. Have the business
   owner sign the acceptance record.
6. Open transactions in the new system only after sign-off. Retain the legacy
   source read-only for the agreed audit period.

## 6. Rollback

If cut-over has not opened to users, stop web and background workers, preserve
the failed database and logs for investigation, and restore the verified
pre-import PostgreSQL and private-media backups as a matched pair. Re-run the
imports only after correcting the source/mapping problem and confirming the
previous batch did not post.

After users have entered live transactions, do not restore an older backup
without an approved loss/recovery decision: it could erase valid transactions.
Stop writes, preserve the current database, notify the business owner and
accountant, and choose a controlled forward correction or a formally approved
restore with transaction replay. Never delete or edit posted financial records
to simulate a rollback.
