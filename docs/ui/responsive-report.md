# Responsive UI Audit

HTML pages audited: **6** across **3** browser(s) and **12** viewport(s).
Finding count: **0**. Registry routes not audited as HTML pages: **223**.

| Check category | Failures after |
|---|---:|

No directly comparable before-run was retained: the earlier audit used a different detector and treated popup fragments as standalone pages. Current results use the same detector across the listed pages, browsers and viewports.

| Page | Viewport | Browser | Finding |
|---|---:|---|---|
| — | — | — | No failures detected. |

## Registry routes excluded from visual checks

These routes are API endpoints, reject GET, do not resolve with the sample URL, or did not return an HTML 200 response during preflight.

| Route | Reason |
|---|---|
| `/accounts/create-role/` | Popup form fragment; rendered in its shared modal host |
| `/accounts/edit-role/1/` | Popup form fragment; rendered in its shared modal host |
| `/accounts/create-user/` | Popup form fragment; rendered in its shared modal host |
| `/accounts/users/edit/1/` | Popup form fragment; rendered in its shared modal host |
| `/accounts/users/delete/1/` | HTTP 405 (text/html; charset=utf-8) |
| `/branch/add/` | Popup form fragment; rendered in its shared modal host |
| `/branch/edit/1/` | Popup form fragment; rendered in its shared modal host |
| `/branch/delete/1/` | HTTP 405 (text/html; charset=utf-8) |
| `/branch/centers/add/` | Popup form fragment; rendered in its shared modal host |
| `/branch/centers/edit/1/` | Popup form fragment; rendered in its shared modal host |
| `/branch/groups/add/` | Popup form fragment; rendered in its shared modal host |
| `/branch/groups/edit/1/` | Popup form fragment; rendered in its shared modal host |
| `/branch/staff/add/` | Popup form fragment; rendered in its shared modal host |
| `/branch/staff/edit/1/` | Popup form fragment; rendered in its shared modal host |
| `/branch/members/add/` | Popup form fragment; rendered in its shared modal host |
| `/branch/members/edit/1/` | Popup form fragment; rendered in its shared modal host |
| `/branch/members/1/` | HTTP 404 (text/html; charset=utf-8) |
| `/branch/members/status/1/` | HTTP 405 (text/html; charset=utf-8) |
| `/branch/members/kyc/1/` | HTTP 404 (text/html; charset=utf-8) |
| `/branch/members/kyc/verify/1/` | HTTP 405 (text/html; charset=utf-8) |
| `/branch/members/photo/1/` | HTTP 404 (text/html; charset=utf-8) |
| `/branch/members/kyc/file/1/` | HTTP 404 (text/html; charset=utf-8) |
| `/branch/day-end/close/` | HTTP 405 (text/html; charset=utf-8) |
| `/branch/day-end/reopen/` | HTTP 405 (text/html; charset=utf-8) |
| `/branch/holidays/add/` | Popup form fragment; rendered in its shared modal host |
| `/branch/holidays/edit/1/` | Popup form fragment; rendered in its shared modal host |
| `/audit/trail/sample/sample/` | HTTP 404 (text/html; charset=utf-8) |
| `/accounting/accounts/add/` | Popup form fragment; rendered in its shared modal host |
| `/accounting/accounts/edit/1/` | Popup form fragment; rendered in its shared modal host |
| `/accounting/fiscal-years/add/` | Popup form fragment; rendered in its shared modal host |
| `/accounting/periods/add/` | Popup form fragment; rendered in its shared modal host |
| `/accounting/periods/1/close/` | HTTP 405 (text/html; charset=utf-8) |
| `/accounting/system-accounts/add/` | Popup form fragment; rendered in its shared modal host |
| `/accounting/system-accounts/1/` | Popup form fragment; rendered in its shared modal host |
| `/accounting/journal-entries/add/` | Popup form fragment; rendered in its shared modal host |
| `/accounting/journal-entries/1/` | HTTP 404 (text/html; charset=utf-8) |
| `/accounting/journal-entries/1/post/` | HTTP 405 (text/html; charset=utf-8) |
| `/accounting/journal-entries/1/reverse/` | HTTP 404 (text/html; charset=utf-8) |
| `/accounting/reconciliation/add/` | Popup form fragment; rendered in its shared modal host |
| `/accounting/reconciliation/1/confirm/` | HTTP 405 (text/html; charset=utf-8) |
| `/savings/products/add/` | Popup form fragment; rendered in its shared modal host |
| `/savings/products/edit/1/` | Popup form fragment; rendered in its shared modal host |
| `/savings/products/1/activate/` | HTTP 405 (text/html; charset=utf-8) |
| `/savings/products/1/deactivate/` | HTTP 405 (text/html; charset=utf-8) |
| `/savings/accounts/add/` | Popup form fragment; rendered in its shared modal host |
| `/savings/accounts/1/close/` | HTTP 405 (text/html; charset=utf-8) |
| `/savings/accounts/1/statement/` | HTTP 404 (text/html; charset=utf-8) |
| `/savings/accounts/1/statement.csv` | HTTP 404 (text/html; charset=utf-8) |
| `/savings/accounts/1/reactivate/` | Popup form fragment; rendered in its shared modal host |
| `/savings/accounts/1/reactivate/submit/` | HTTP 405 (text/html; charset=utf-8) |
| `/savings/transactions/deposit/` | Popup form fragment; rendered in its shared modal host |
| `/savings/transactions/deposit/post/` | HTTP 405 (text/html; charset=utf-8) |
| `/savings/transactions/withdraw/` | Popup form fragment; rendered in its shared modal host |
| `/savings/transactions/withdraw/post/` | HTTP 405 (text/html; charset=utf-8) |
| `/savings/transactions/fee/` | Popup form fragment; rendered in its shared modal host |
| `/savings/transactions/fee/post/` | HTTP 405 (text/html; charset=utf-8) |
| `/savings/transactions/interest/` | Popup form fragment; rendered in its shared modal host |
| `/savings/transactions/interest/post/` | HTTP 405 (text/html; charset=utf-8) |
| `/savings/transactions/1/approve/` | HTTP 405 (text/html; charset=utf-8) |
| `/savings/transactions/1/reject/` | Popup form fragment; rendered in its shared modal host |
| `/savings/transactions/1/reject/post/` | HTTP 405 (text/html; charset=utf-8) |
| `/savings/transactions/1/reverse/` | Popup form fragment; rendered in its shared modal host |
| `/savings/transactions/1/reverse/post/` | HTTP 405 (text/html; charset=utf-8) |
| `/loans/products/add/` | Popup form fragment; rendered in its shared modal host |
| `/loans/products/edit/1/` | Popup form fragment; rendered in its shared modal host |
| `/loans/products/1/activate/` | HTTP 405 (text/html; charset=utf-8) |
| `/loans/products/1/deactivate/` | HTTP 405 (text/html; charset=utf-8) |
| `/loans/business-rules/approval-tiers/add/` | Popup form fragment; rendered in its shared modal host |
| `/loans/business-rules/approval-tiers/edit/1/` | Popup form fragment; rendered in its shared modal host |
| `/loans/business-rules/par-buckets/add/` | Popup form fragment; rendered in its shared modal host |
| `/loans/business-rules/par-buckets/edit/1/` | Popup form fragment; rendered in its shared modal host |
| `/loans/classification/export/excel/` | HTTP 200 (application/vnd.openxmlformats-officedocument.spreadsheetml.sheet) |
| `/loans/classification/export/pdf/` | HTTP 200 (application/pdf) |
| `/loans/applications/add/` | Popup form fragment; rendered in its shared modal host |
| `/loans/applications/1/submit/` | HTTP 405 (text/html; charset=utf-8) |
| `/loans/applications/1/review/` | Popup form fragment; rendered in its shared modal host |
| `/loans/applications/1/cancel/` | HTTP 405 (text/html; charset=utf-8) |
| `/loans/applications/1/disburse/` | Popup form fragment; rendered in its shared modal host |
| `/loans/1/repay/` | Popup form fragment; rendered in its shared modal host |
| `/loans/1/schedule/` | HTTP 404 (text/html; charset=utf-8) |
| `/loans/1/statement/` | HTTP 404 (text/html; charset=utf-8) |
| `/loans/1/history/` | HTTP 404 (text/html; charset=utf-8) |
| `/loans/1/reschedule/` | Popup form fragment; rendered in its shared modal host |
| `/loans/1/settle/` | Popup form fragment; rendered in its shared modal host |
| `/loans/1/waive-interest/` | Popup form fragment; rendered in its shared modal host |
| `/loans/1/write-off/` | Popup form fragment; rendered in its shared modal host |
| `/loans/1/recovery/` | Popup form fragment; rendered in its shared modal host |
| `/collections/sheets/generate/` | Popup form fragment; rendered in its shared modal host |
| `/collections/sheets/1/` | HTTP 404 (text/html; charset=utf-8) |
| `/collections/sheets/1/start/` | HTTP 405 (text/html; charset=utf-8) |
| `/collections/sheets/1/items/1/` | HTTP 405 (text/html; charset=utf-8) |
| `/collections/sheets/1/submit/` | HTTP 405 (text/html; charset=utf-8) |
| `/collections/sheets/1/cancel/` | HTTP 405 (text/html; charset=utf-8) |
| `/collections/sheets/1/reversal/request/` | HTTP 405 (text/html; charset=utf-8) |
| `/collections/reversals/1/approve/` | HTTP 405 (text/html; charset=utf-8) |
| `/collections/sheets/1/print/` | HTTP 404 (text/html; charset=utf-8) |
| `/collections/reconciliation/1/reconcile/` | HTTP 405 (text/html; charset=utf-8) |
| `/collections/reconciliation/1/post/` | HTTP 405 (text/html; charset=utf-8) |
| `/collections/reports/export/excel/` | HTTP 200 (application/vnd.openxmlformats-officedocument.spreadsheetml.sheet) |
| `/collections/reports/export/pdf/` | HTTP 200 (application/pdf) |
| `/reports/trial-balance/data/` | HTTP 200 (application/json) |
| `/reports/trial-balance/export/excel/` | HTTP 200 (application/vnd.openxmlformats-officedocument.spreadsheetml.sheet) |
| `/reports/trial-balance/export/pdf/` | HTTP 200 (application/pdf) |
| `/reports/general-ledger/data/` | HTTP 200 (application/json) |
| `/reports/general-ledger/export/excel/` | HTTP 200 (application/vnd.openxmlformats-officedocument.spreadsheetml.sheet) |
| `/reports/general-ledger/export/pdf/` | HTTP 200 (application/pdf) |
| `/reports/cash-book/data/` | HTTP 200 (application/json) |
| `/reports/cash-book/export/excel/` | HTTP 200 (application/vnd.openxmlformats-officedocument.spreadsheetml.sheet) |
| `/reports/cash-book/export/pdf/` | HTTP 200 (application/pdf) |
| `/reports/income-statement/data/` | HTTP 200 (application/json) |
| `/reports/income-statement/export/excel/` | HTTP 200 (application/vnd.openxmlformats-officedocument.spreadsheetml.sheet) |
| `/reports/income-statement/export/pdf/` | HTTP 200 (application/pdf) |
| `/reports/balance-sheet/data/` | HTTP 200 (application/json) |
| `/reports/balance-sheet/export/excel/` | HTTP 200 (application/vnd.openxmlformats-officedocument.spreadsheetml.sheet) |
| `/reports/balance-sheet/export/pdf/` | HTTP 200 (application/pdf) |
| `/reports/receipts-payments/data/` | HTTP 200 (application/json) |
| `/reports/receipts-payments/export/excel/` | HTTP 200 (application/vnd.openxmlformats-officedocument.spreadsheetml.sheet) |
| `/reports/receipts-payments/export/pdf/` | HTTP 200 (application/pdf) |
| `/reports/disbursement-register/data/` | HTTP 200 (application/json) |
| `/reports/disbursement-register/export/excel/` | HTTP 200 (application/vnd.openxmlformats-officedocument.spreadsheetml.sheet) |
| `/reports/disbursement-register/export/pdf/` | HTTP 200 (application/pdf) |
| `/reports/outstanding-loans/data/` | HTTP 200 (application/json) |
| `/reports/outstanding-loans/export/excel/` | HTTP 200 (application/vnd.openxmlformats-officedocument.spreadsheetml.sheet) |
| `/reports/outstanding-loans/export/pdf/` | HTTP 200 (application/pdf) |
| `/reports/overdue-loans/data/` | HTTP 200 (application/json) |
| `/reports/overdue-loans/export/excel/` | HTTP 200 (application/vnd.openxmlformats-officedocument.spreadsheetml.sheet) |
| `/reports/overdue-loans/export/pdf/` | HTTP 200 (application/pdf) |
| `/reports/aging/data/` | HTTP 200 (application/json) |
| `/reports/aging/export/excel/` | HTTP 200 (application/vnd.openxmlformats-officedocument.spreadsheetml.sheet) |
| `/reports/aging/export/pdf/` | HTTP 200 (application/pdf) |
| `/reports/write-offs/data/` | HTTP 200 (application/json) |
| `/reports/write-offs/export/excel/` | HTTP 200 (application/vnd.openxmlformats-officedocument.spreadsheetml.sheet) |
| `/reports/write-offs/export/pdf/` | HTTP 200 (application/pdf) |
| `/reports/repayment-schedule/data/` | HTTP 200 (application/json) |
| `/reports/repayment-schedule/export/excel/` | HTTP 200 (application/vnd.openxmlformats-officedocument.spreadsheetml.sheet) |
| `/reports/repayment-schedule/export/pdf/` | HTTP 200 (application/pdf) |
| `/reports/portfolio-at-risk/data/` | HTTP 200 (application/json) |
| `/reports/portfolio-at-risk/export/excel/` | HTTP 200 (application/vnd.openxmlformats-officedocument.spreadsheetml.sheet) |
| `/reports/portfolio-at-risk/export/pdf/` | HTTP 200 (application/pdf) |
| `/reports/loan-statement/data/` | HTTP 200 (application/json) |
| `/reports/loan-statement/export/excel/` | HTTP 200 (application/vnd.openxmlformats-officedocument.spreadsheetml.sheet) |
| `/reports/loan-statement/export/pdf/` | HTTP 200 (application/pdf) |
| `/reports/classification/data/` | HTTP 200 (application/json) |
| `/reports/classification/export/excel/` | HTTP 200 (application/vnd.openxmlformats-officedocument.spreadsheetml.sheet) |
| `/reports/classification/export/pdf/` | HTTP 200 (application/pdf) |
| `/reports/account-list/data/` | HTTP 200 (application/json) |
| `/reports/account-list/export/excel/` | HTTP 200 (application/vnd.openxmlformats-officedocument.spreadsheetml.sheet) |
| `/reports/account-list/export/pdf/` | HTTP 200 (application/pdf) |
| `/reports/transaction-register/data/` | HTTP 200 (application/json) |
| `/reports/transaction-register/export/excel/` | HTTP 200 (application/vnd.openxmlformats-officedocument.spreadsheetml.sheet) |
| `/reports/transaction-register/export/pdf/` | HTTP 200 (application/pdf) |
| `/reports/balance-summary/data/` | HTTP 200 (application/json) |
| `/reports/balance-summary/export/excel/` | HTTP 200 (application/vnd.openxmlformats-officedocument.spreadsheetml.sheet) |
| `/reports/balance-summary/export/pdf/` | HTTP 200 (application/pdf) |
| `/reports/interest-posted/data/` | HTTP 200 (application/json) |
| `/reports/interest-posted/export/excel/` | HTTP 200 (application/vnd.openxmlformats-officedocument.spreadsheetml.sheet) |
| `/reports/interest-posted/export/pdf/` | HTTP 200 (application/pdf) |
| `/reports/dormant-accounts/data/` | HTTP 200 (application/json) |
| `/reports/dormant-accounts/export/excel/` | HTTP 200 (application/vnd.openxmlformats-officedocument.spreadsheetml.sheet) |
| `/reports/dormant-accounts/export/pdf/` | HTTP 200 (application/pdf) |
| `/reports/member-list/data/` | HTTP 200 (application/json) |
| `/reports/member-list/export/excel/` | HTTP 200 (application/vnd.openxmlformats-officedocument.spreadsheetml.sheet) |
| `/reports/member-list/export/pdf/` | HTTP 200 (application/pdf) |
| `/reports/new-members/data/` | HTTP 200 (application/json) |
| `/reports/new-members/export/excel/` | HTTP 200 (application/vnd.openxmlformats-officedocument.spreadsheetml.sheet) |
| `/reports/new-members/export/pdf/` | HTTP 200 (application/pdf) |
| `/reports/status-summary/data/` | HTTP 200 (application/json) |
| `/reports/status-summary/export/excel/` | HTTP 200 (application/vnd.openxmlformats-officedocument.spreadsheetml.sheet) |
| `/reports/status-summary/export/pdf/` | HTTP 200 (application/pdf) |
| `/reports/kyc-pending-expired/data/` | HTTP 200 (application/json) |
| `/reports/kyc-pending-expired/export/excel/` | HTTP 200 (application/vnd.openxmlformats-officedocument.spreadsheetml.sheet) |
| `/reports/kyc-pending-expired/export/pdf/` | HTTP 200 (application/pdf) |
| `/reports/member-statement/data/` | HTTP 200 (application/json) |
| `/reports/member-statement/export/excel/` | HTTP 200 (application/vnd.openxmlformats-officedocument.spreadsheetml.sheet) |
| `/reports/member-statement/export/pdf/` | HTTP 200 (application/pdf) |
| `/reports/collection-summary/data/` | HTTP 200 (application/json) |
| `/reports/collection-summary/export/excel/` | HTTP 200 (application/vnd.openxmlformats-officedocument.spreadsheetml.sheet) |
| `/reports/collection-summary/export/pdf/` | HTTP 200 (application/pdf) |
| `/reports/collection-register/data/` | HTTP 200 (application/json) |
| `/reports/collection-register/export/excel/` | HTTP 200 (application/vnd.openxmlformats-officedocument.spreadsheetml.sheet) |
| `/reports/collection-register/export/pdf/` | HTTP 200 (application/pdf) |
| `/reports/collector-performance/data/` | HTTP 200 (application/json) |
| `/reports/collector-performance/export/excel/` | HTTP 200 (application/vnd.openxmlformats-officedocument.spreadsheetml.sheet) |
| `/reports/collector-performance/export/pdf/` | HTTP 200 (application/pdf) |
| `/reports/collection-efficiency/data/` | HTTP 200 (application/json) |
| `/reports/collection-efficiency/export/excel/` | HTTP 200 (application/vnd.openxmlformats-officedocument.spreadsheetml.sheet) |
| `/reports/collection-efficiency/export/pdf/` | HTTP 200 (application/pdf) |
| `/reports/shortage-excess/data/` | HTTP 200 (application/json) |
| `/reports/shortage-excess/export/excel/` | HTTP 200 (application/vnd.openxmlformats-officedocument.spreadsheetml.sheet) |
| `/reports/shortage-excess/export/pdf/` | HTTP 200 (application/pdf) |
| `/reports/user-access-review/data/` | HTTP 200 (application/json) |
| `/reports/user-access-review/export/excel/` | HTTP 200 (application/vnd.openxmlformats-officedocument.spreadsheetml.sheet) |
| `/reports/user-access-review/export/pdf/` | HTTP 200 (application/pdf) |
| `/reports/role-permission-history/data/` | HTTP 200 (application/json) |
| `/reports/role-permission-history/export/excel/` | HTTP 200 (application/vnd.openxmlformats-officedocument.spreadsheetml.sheet) |
| `/reports/role-permission-history/export/pdf/` | HTTP 200 (application/pdf) |
| `/reports/privileged-actions/data/` | HTTP 200 (application/json) |
| `/reports/privileged-actions/export/excel/` | HTTP 200 (application/vnd.openxmlformats-officedocument.spreadsheetml.sheet) |
| `/reports/privileged-actions/export/pdf/` | HTTP 200 (application/pdf) |
| `/reports/failed-logins/data/` | HTTP 200 (application/json) |
| `/reports/failed-logins/export/excel/` | HTTP 200 (application/vnd.openxmlformats-officedocument.spreadsheetml.sheet) |
| `/reports/failed-logins/export/pdf/` | HTTP 200 (application/pdf) |
| `/reports/day-reopen-reversals/data/` | HTTP 200 (application/json) |
| `/reports/day-reopen-reversals/export/excel/` | HTTP 200 (application/vnd.openxmlformats-officedocument.spreadsheetml.sheet) |
| `/reports/day-reopen-reversals/export/pdf/` | HTTP 200 (application/pdf) |
| `/reports/kyc-completeness/data/` | HTTP 200 (application/json) |
| `/reports/kyc-completeness/export/excel/` | HTTP 200 (application/vnd.openxmlformats-officedocument.spreadsheetml.sheet) |
| `/reports/kyc-completeness/export/pdf/` | HTTP 200 (application/pdf) |
| `/settings/system/logo/` | HTTP 404 (text/html; charset=utf-8) |
| `/settings/system/save/` | HTTP 405 (text/html; charset=utf-8) |
| `/settings/organization/save/` | HTTP 405 (text/html; charset=utf-8) |
| `/settings/preferences/save/` | HTTP 405 (text/html; charset=utf-8) |
| `/settings/business-rules/save/` | HTTP 405 (text/html; charset=utf-8) |
| `/settings/notifications/templates/save/` | HTTP 405 (text/html; charset=utf-8) |
| `/settings/notifications/schedule/save/` | HTTP 405 (text/html; charset=utf-8) |
| `/notifications/preferences/save/` | HTTP 405 (text/html; charset=utf-8) |
| `/notifications/read/1/` | HTTP 405 (text/html; charset=utf-8) |
| `/imports/upload/` | HTTP 405 (text/html; charset=utf-8) |
| `/imports/validate/1/` | HTTP 405 (text/html; charset=utf-8) |
| `/imports/errors/1/` | HTTP 404 (text/html; charset=utf-8) |
| `/imports/confirm/1/` | HTTP 405 (text/html; charset=utf-8) |
| `/imports/approve/1/` | HTTP 405 (text/html; charset=utf-8) |
| `/imports/template/sample/` | HTTP 404 (text/html; charset=utf-8) |
