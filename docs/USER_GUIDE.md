# User Guide

This guide describes the workflows that are present in the application. Menus
and actions appear only when the signed-in user has the matching permission.
Choose the correct active branch before entering or reviewing records. Privileged
users must complete MFA enrollment when prompted; sensitive actions may ask for
an MFA code again.

## Field officer

### Register a member and complete KYC

1. Open **Members → Members** and choose **Add member**.
2. Enter the member's identity and contact details, select the branch and
   admission date, then save.
   - **Expected result:** the new member appears in the branch member list with
     a generated member code and an audit record.
3. Open the member record and choose **KYC**. Add the identity documents and
   submit them for verification.
   - **Expected result:** each document is marked pending until an authorized
     verifier accepts or rejects it.
4. Confirm the member's contact, branch and KYC details on the member detail
   page before starting a financial workflow.

### Record a collection

1. Open **Collections → Collection sheets** and choose **Generate**.
2. Select the branch, center and business date, then generate the sheet.
   - **Expected result:** the sheet contains eligible active loans and their
     scheduled amounts.
3. Open the sheet, choose **Start**, and record each member's actual amount.
   Save each item as it is entered.
   - **Expected result:** the sheet retains the entered amounts and shows its
     current status.
4. Check the totals against the cash collected, then choose **Submit** and hand
   the cash and sheet reference to the cashier.
   - **Expected result:** the sheet is submitted and is ready for cashier
     reconciliation; do not post it yourself unless that permission is
     explicitly assigned.

## Cashier

### Receive and post a collection sheet

1. Open **Collections → Reconciliation** and select the submitted sheet.
2. Enter the cash counted and any required variance explanation; save the
   reconciliation.
   - **Expected result:** the system shows the sheet total, cash count and
     variance together.
3. Resolve any discrepancy with the field officer and manager. When authorized,
   post the sheet.
   - **Expected result:** loan payments and the balanced journal post once; the
     sheet becomes posted and cannot be edited.

### Post a savings deposit or withdrawal

1. Open **Savings → Transactions** and choose **Deposit** or **Withdraw**.
2. Find the account, enter the amount, transaction date, channel and required
   reference/narration, then submit.
   - **Expected result:** a deposit increases the account balance; a withdrawal
     decreases it only when the available-balance and product rules allow it.
3. For a withdrawal awaiting approval, give the approver the transaction
   reference; do not submit it again.
   - **Expected result:** the transaction is either approved and posted once or
     rejected with its balance unchanged.
4. Open **Savings → Accounts**, find the account and view its statement to
   confirm the posted transaction and balance.

### Receive a direct loan repayment

1. Open **Loans → Portfolio**, find the loan, and open its repayment action.
2. Enter the amount, date and cash/bank channel, then submit once.
   - **Expected result:** the payment is allocated to due penalties, fees,
     interest and principal in the configured order, and the loan statement and
     ledger reflect the same posting.
3. Use the transaction reference to check the posted result; use a reversal
   workflow for an error rather than repeating or editing a posted payment.

## Branch manager

### Review and disburse a loan

1. Open **Loans → Applications** and select an application assigned to your
   branch.
2. Review member eligibility, verified KYC, product terms, repayment capacity
   and any required guarantor or collateral. Choose **Review** and approve or
   return it with a clear comment.
   - **Expected result:** the application status and review history record the
     decision.
3. For an approved application, open **Loans → Disbursements**, select the
   application, confirm the amount/date/channel and required checker approval,
   then disburse.
   - **Expected result:** one active loan, a complete repayment schedule and a
     balanced disbursement journal are created.

### Reverse a transaction or collection

1. Open the original savings transaction and choose **Reverse**, or open the
   collection sheet and choose **Request reversal**. Loan payments posted from
   a collection sheet are corrected through that sheet's reversal workflow.
2. Enter the effective date and a specific reason. Complete MFA re-verification
   if prompted.
   - **Expected result:** a reversal request is recorded; the original posted
     record remains unchanged.
3. A different authorized checker reviews and approves the request.
   - **Expected result:** a separate correcting journal and audit entry are
     posted once. The maker cannot approve their own request.

### Close or reopen a business day

1. Open **Organization → Day-end closing** and select the active branch.
2. Review the checklist, unresolved collection sheets, cash variances and
   pending postings. Close the day only after reconciling all exceptions.
   - **Expected result:** the branch business date advances and posting to the
     closed date is blocked.
3. To reopen a closed day, use the reopen action, enter the reason, complete
   the required checker/MFA step, and submit for approval.
   - **Expected result:** the reopen is audited; the business date changes only
     after a different authorized approver accepts it.

## Accountant

### Prepare accounting controls

1. Open **Accounting → Chart of accounts** and verify that the required,
   active, postable accounts exist.
2. Open **Accounting → System account mappings** and verify the mappings used by
   cash, savings and loan transactions. For loan opening imports, confirm both
   **Loans to Members** (asset) and **Opening Balance Equity** (equity).
   - **Expected result:** each mapping points to an active, postable account of
     its required type.
3. Open **Accounting → Fiscal years** and confirm the fiscal year and posting
   period are open for the transaction dates.

### Post and reconcile the month

1. Open **Accounting → Journal entries**, create an authorized journal, enter
   equal total debits and credits, and submit/post using the required checker
   workflow.
   - **Expected result:** the journal is posted once and appears in the ledger.
2. Open **Accounting → Reconciliation**, choose the account and statement date,
   compare the statement with the system balance, explain any variance and
   submit/confirm the reconciliation.
   - **Expected result:** a confirmed reconciliation records the balance and
     explanation; unresolved variance blocks applicable backdated postings.
3. Open **Reports** at `/reports/` and run the trial balance, balance sheet,
   income statement and required branch/loan/savings reports for the closed
   month.
   - **Expected result:** the trial balance balances, report totals agree with
     the ledgers and subledgers, and exports use the same filters as the page.
4. Close the accounting period only after all required postings and reviews are
   complete.

## Administrator

### Create a least-privilege user

1. Open **Administration → Roles** and create or edit the role. Select only the
   route permissions needed for the user's job.
2. Open **Administration → Users**, create the named user, assign the role and
   permitted branch, and save.
   - **Expected result:** the user can sign in only to permitted pages and
     accessible branches; permissions are audited.
3. Have the user sign in and complete MFA enrollment if required. Verify access
   with the user's account rather than granting extra permissions to bypass a
   denied action.

### Change settings safely

1. Open **Administration → Settings** and select the specific configuration
   area.
2. Review the current value and downstream effect, change only the approved
   setting, then save.
   - **Expected result:** the saved configuration is visible after refresh and
     the change is audited.
3. For emergency MFA recovery, use the documented server-only management
   command in [the deployment runbook](./DEPLOYMENT.md); do not disable MFA or
   edit database rows by hand.

## Auditor

### Review activity and controls

1. Open **Audit** and filter by date, actor, branch, entity or action. Open the
   relevant record trail and compare before/after values with the source
   transaction.
   - **Expected result:** each state change links to its actor, timestamp,
     branch and related record where available.
2. Open **Reports** at `/reports/` and run the permitted audit, privileged
   action, failed login, reversal/day-reopen, KYC and financial reports.
   - **Expected result:** results are limited to permitted branches and report
     filters; exports match the displayed selection.
3. Record exceptions and evidence outside the system's immutable transaction
   history, then send remediation items to the responsible manager.
   - **Expected result:** no auditor account is used to change operational
     records, roles or balances.

## Safe operating rules

- Never share an account, password, MFA code or recovery code.
- Check the active branch, member/account identity, date and amount before every
  financial submission.
- Do not repeat a submission after a timeout until its status/reference has
  been checked; idempotency protects supported postings, but the record should
  still be verified.
- Posted financial entries are corrected by an authorized reversal, not by
  editing or deleting history.
- Report unexpected balances, access-denied screens, or request IDs to the
  administrator.
