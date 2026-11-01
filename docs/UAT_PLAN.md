# User Acceptance Test Plan

Run this plan in a production-like UAT environment with synthetic data, current
backups and staff accounts matching the assigned roles. Record the tester,
date, environment and evidence for each scenario. A scenario passes only when
the expected result is observed and its evidence is retained.

## End-to-end scenarios

| ID | Scenario and steps | Expected result / acceptance evidence | Pass | Fail |
|---|---|---|---|---|
| UAT-01 | As a field officer, create a member, add identity documents, and submit KYC. As a verifier, review and approve the documents. | Member is branch-scoped, has one member code, KYC status/history is correct, and unauthorized branches cannot open the record. | [ ] | [ ] |
| UAT-02 | As an authorized clerk, open individual savings for an active member; post a deposit; view the account statement and balance report. | Account belongs to the member/branch; balance, transaction and journal agree; the transaction appears once. | [ ] | [ ] |
| UAT-03 | Post an allowed savings withdrawal, then attempt an amount above the available balance or product limit. | Allowed withdrawal is posted once; rejected withdrawal leaves the balance and ledger unchanged and returns a clear validation error. | [ ] | [ ] |
| UAT-04 | Create a loan application, submit it, have an authorized manager review it, then disburse through the maker-checker flow. | Application history shows distinct maker/checker; one active loan and schedule exist; journal debits/credits balance and loan subledger agrees. | [ ] | [ ] |
| UAT-05 | Repay a loan with due principal, interest and penalty; open the statement and portfolio/PAR report. | Payment allocation follows configured order; outstanding principal, installment balances, penalties, journal and PAR update consistently. | [ ] | [ ] |
| UAT-06 | Generate a collection sheet for a center, start it, enter member payments, submit it, reconcile cash and post it. | Only eligible branch/center loans appear; cash variance is explicit; posting creates one payment per item and a balanced journal. | [ ] | [ ] |
| UAT-07 | Request a reversal of a posted savings/loan/collection transaction with a reason; approve it as a different checker. | Original remains immutable; approval creates one correcting transaction/journal, updates derived balances, and records the maker, checker and reason. | [ ] | [ ] |
| UAT-08 | Close a branch business day after completing its checklist; attempt a posting to the closed date; reopen with a reason and a different checker. | Closed-date posting is denied; reopen requires permission, reason, MFA re-verification and distinct approval; both actions appear in audit history. | [ ] | [ ] |
| UAT-09 | At month end, run trial balance, general ledger, balance sheet, income statement, savings reconciliation, loan portfolio/PAR and collection reports; export required reports. | Trial balance is balanced; report filters and totals reconcile to source subledgers; exports contain the same selected period and branch. | [ ] | [ ] |
| UAT-10 | As an auditor, review audit logs, user access, privileged actions, failed logins, reversals and day reopens. | Read-only access is enforced; actor, time, branch, reason and related records are traceable; unauthorized mutations are denied. | [ ] | [ ] |
| UAT-11 | As an administrator, create a least-privilege role/user, grant one branch, then remove a permission and retry the route. | User sees only granted routes/branches; permission revocation takes effect; changes are audited; the user cannot self-assign access. | [ ] | [ ] |
| UAT-12 | Upload a valid loan opening workbook, inspect dry-run results, confirm as maker and approve as another user. Compare schedule, principal, accrued interest, overdue count, penalties and ledger. | Import is atomic and file-hash idempotent; principal-only opening journal balances to Opening Balance Equity; schedule/PAR and loan subledger reconcile. | [ ] | [ ] |
| UAT-13 | Upload an invalid, malformed, macro-enabled, oversized or formula-leading workbook; inspect its error report. | Unsafe workbook is rejected or row errors are reported without formula execution; no financial or member records are partially created. | [ ] | [ ] |
| UAT-14 | Attempt duplicate approval/posting, a maker's own approval, a forged cross-branch ID, a GET mutation and a direct URL without permission. | Requests are rejected or return the existing idempotent result; no duplicate journal/payment, data disclosure or state change occurs. | [ ] | [ ] |
| UAT-15 | As a privileged user, log in without enrolled MFA, try direct/AJAX page access before MFA, reuse a TOTP code, and use one recovery code twice. | Enrollment is mandatory; no page/action bypasses MFA; replay is rejected; recovery code is single-use; lockout/rate limits apply. | [ ] | [ ] |
| UAT-16 | Force a late failure while importing two loans and repeat an import upload with the same file. | Late failure rolls back every loan, installment, penalty, journal and batch state; same file hash does not create a second batch/posting. | [ ] | [ ] |

## Acceptance checklist

- [ ] All scenarios above pass; no unresolved high-severity defect remains.
- [ ] PostgreSQL test suite, migrations and current quality/security checks pass
  in the release build.
- [ ] Role permissions and branch boundaries have been reviewed by the business
  owner; each tester has a named account.
- [ ] Opening balances reconcile by branch and control account; unexplained
  differences are not accepted as a pass.
- [ ] Staff have completed role-specific training and can repeat their daily
  workflows using [the user guide](./USER_GUIDE.md).
- [ ] Restore, incident escalation and support contacts have been exercised or
  verified before production cut-over.

**Acceptance decision:** Pass / Fail  
**Business owner:** ____________________  
**Date:** ____________________  
**Outstanding issues and approved exceptions:** ____________________
