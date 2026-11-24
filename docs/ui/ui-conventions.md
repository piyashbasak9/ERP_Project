# UI Conventions and Route Audit

## Audit status

The route registry classifies **317 routes**: **149 page routes** and **168 non-page routes**. All **27 list routes** use the shared ListPage template and pass its source checks. The UI render test attempted every page route as a superuser; **34 object-dependent or non-HTML routes could not render** because the sample test data does not contain matching records. The cross-browser responsive smoke covered **85 available HTML pages** across Chromium, Firefox and WebKit at 390×844, 1024×768 and 1366×768 with **zero detected findings**. The identical preceding run found two Firefox mobile title/grid boundary overlaps (before: 2; after: 0), fixed by adding a 1px gap without relaxing the detector. The complete 10-viewport and 125%/150% zoom matrix remains unverified. Popup fragments and object-dependent route variants still need complete visual coverage, and non-list pages still need type-specific convention verification. Overall completion remains **partial**.

Before-status values are based on the prior code review, not a saved screenshot baseline. The earlier responsive snapshot used a different detector and route set, so its counts are not directly comparable; current responsive results are in [responsive-report.md](./responsive-report.md).

## Convention checklist

1. **Shell:** shared organization header and name, permission-derived menu, status bar with PRT timer and organization text; no legacy sidebar.
2. **Title bar:** page title left; permitted Add, Search, Export and Print actions right.
3. **Filters:** shared compact panel; GET values in the URL, active chips, Reset, and Enter submission.
4. **Grid:** ListPage with server-side paging, sorting and filtering; sticky header, row number, conditional selection, compact zebra rows, filled-height layout, resizing/chooser, standard formatting and escaped cells.
5. **Grid footer:** DLT timer, pager, page-size selector and `View x - y of z`.
6. **Row actions:** permission-aware links; destructive actions use CSRF-protected POST, confirmation and audit.
7. **Create/edit:** AJAX popup fragments in the dense style; long forms use bounded wide dialogs with sections or tabs.
8. **Messages:** top-middle five-second success/error toasts; no `alert()` or replacement inline messages.
9. **States:** consistent empty, loading and retryable error states.
10. **Responsive:** declared column priorities, phone cards, off-canvas menu, full-screen phone popups and no page-level horizontal overflow.
11. **Accessibility:** labels, ARIA, visible focus, keyboard use and WCAG AA contrast.
12. **Security:** strict CSP; no inline scripts or CDN; escaped output, CSRF on POST; permissions and branch scope unchanged.

## Route inventory

`Shared ListPage` means the route is registered to the shared template and has source-level coverage; `Pending audit` is not verified; `N/A` is not a user-facing page. Non-page routes are exempt from layout checks because they are JSON, downloads, or state-changing endpoints. Popup form fragments are embedded in the shared modal, so their host supplies the page shell.

| Route | Path | Type | Status before | Status after | Exemption / reason |
|---|---|---|---|---|---|
| `Module_Accounting_account_add` | `/accounting/accounts/add/` | `popup_form_fragment` | Not audited | Form marker verified where renderable; full audit pending | Fragment is hosted inside the shared popup; no standalone shell |
| `Module_Accounting_account_edit` | `/accounting/accounts/edit/<int:pk>/` | `popup_form_fragment` | Not audited | Form marker verified where renderable; full audit pending | Fragment is hosted inside the shared popup; no standalone shell |
| `Module_Accounting_account_list` | `/accounting/accounts/` | `list_page` | Shared ListPage | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Accounting_fiscal_year_add` | `/accounting/fiscal-years/add/` | `popup_form_fragment` | Not audited | Form marker verified where renderable; full audit pending | Fragment is hosted inside the shared popup; no standalone shell |
| `Module_Accounting_fiscal_years` | `/accounting/fiscal-years/` | `special_screen` | Not audited | Shared title bar and permission-aware actions; period grouping and POST close action retained; cross-browser smoke passed at 390x844, 1024x768 and 1366x768 | — |
| `Module_Accounting_journal_add` | `/accounting/journal-entries/add/` | `popup_form_fragment` | Not audited | Form marker verified where renderable; full audit pending | Fragment is hosted inside the shared popup; no standalone shell |
| `Module_Accounting_journal_detail` | `/accounting/journal-entries/<int:pk>/` | `detail_statement_page` | Not audited | Pending type-specific and responsive audit | — |
| `Module_Accounting_journal_list` | `/accounting/journal-entries/` | `list_page` | Shared ListPage | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Accounting_journal_post` | `/accounting/journal-entries/<int:pk>/post/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Accounting_journal_reverse` | `/accounting/journal-entries/<int:pk>/reverse/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Accounting_period_add` | `/accounting/periods/add/` | `popup_form_fragment` | Not audited | Form marker verified where renderable; full audit pending | Fragment is hosted inside the shared popup; no standalone shell |
| `Module_Accounting_period_close` | `/accounting/periods/<int:pk>/close/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Accounting_reconciliation_add` | `/accounting/reconciliation/add/` | `popup_form_fragment` | Not audited | Form marker verified where renderable; full audit pending | Fragment is hosted inside the shared popup; no standalone shell |
| `Module_Accounting_reconciliation_confirm` | `/accounting/reconciliation/<int:pk>/confirm/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Accounting_reconciliation_list` | `/accounting/reconciliation/` | `list_page` | Legacy list | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Accounting_system_account_add` | `/accounting/system-accounts/add/` | `popup_form_fragment` | Not audited | Form marker verified where renderable; full audit pending | Fragment is hosted inside the shared popup; no standalone shell |
| `Module_Accounting_system_account_edit` | `/accounting/system-accounts/<int:pk>/` | `popup_form_fragment` | Not audited | Form marker verified where renderable; full audit pending | Fragment is hosted inside the shared popup; no standalone shell |
| `Module_Accounting_system_accounts` | `/accounting/system-accounts/` | `list_page` | Legacy list | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Accounting_trial_balance` | `/accounting/trial-balance/` | `report_page` | Not audited | Shared report title/search bar, reset, permission-gated exports and empty state; cross-browser smoke passed at 390x844, 1024x768 and 1366x768 | — |
| `Module_Audit_dashboard` | `/audit/dashboard/` | `dashboard` | Not audited | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Audit_events` | `/audit/events/` | `list_page` | Shared ListPage | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Audit_logs` | `/audit/logs/` | `list_page` | Shared ListPage | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Audit_trail` | `/audit/trail/<str:entity>/<str:entity_id>/` | `detail_statement_page` | Not audited | Pending type-specific and responsive audit | — |
| `Module_Auth_change_password` | `/accounts/password/change/` | `auth_page` | Not audited | Pending type-specific and responsive audit | — |
| `Module_Auth_change_password_done` | `/accounts/password/change/done/` | `auth_page` | Not audited | Pending type-specific and responsive audit | — |
| `Module_Auth_create_role` | `/accounts/create-role/` | `popup_form_fragment` | Not audited | Form marker verified where renderable; full audit pending | Fragment is hosted inside the shared popup; no standalone shell |
| `Module_Auth_create_user` | `/accounts/create-user/` | `popup_form_fragment` | Not audited | Form marker verified where renderable; full audit pending | Fragment is hosted inside the shared popup; no standalone shell |
| `Module_Auth_delete_user` | `/accounts/users/delete/<int:pk>/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Auth_edit_role` | `/accounts/edit-role/<int:pk>/` | `popup_form_fragment` | Not audited | Form marker verified where renderable; full audit pending | Fragment is hosted inside the shared popup; no standalone shell |
| `Module_Auth_edit_user` | `/accounts/users/edit/<int:pk>/` | `popup_form_fragment` | Not audited | Form marker verified where renderable; full audit pending | Fragment is hosted inside the shared popup; no standalone shell |
| `Module_Auth_list_roles` | `/accounts/roles/` | `list_page` | Shared ListPage | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Auth_list_users` | `/accounts/users/` | `list_page` | Shared ListPage | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Auth_login` | `/accounts/login/` | `auth_page` | Not audited | Pending type-specific and responsive audit | — |
| `Module_Auth_logout` | `/accounts/logout/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_BranchHoliday_create` | `/branch/holidays/add/` | `popup_form_fragment` | Not audited | Form marker verified where renderable; full audit pending | Fragment is hosted inside the shared popup; no standalone shell |
| `Module_BranchHoliday_edit` | `/branch/holidays/edit/<int:pk>/` | `popup_form_fragment` | Not audited | Form marker verified where renderable; full audit pending | Fragment is hosted inside the shared popup; no standalone shell |
| `Module_BranchHoliday_list` | `/branch/holidays/` | `list_page` | Legacy list | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Branch_add_branch` | `/branch/add/` | `popup_form_fragment` | Not audited | Form marker verified where renderable; full audit pending | Fragment is hosted inside the shared popup; no standalone shell |
| `Module_Branch_day_end_checklist` | `/branch/day-end/` | `special_screen` | Not audited | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768; type-specific convention verification pending | — |
| `Module_Branch_day_end_close` | `/branch/day-end/close/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Branch_day_end_reopen` | `/branch/day-end/reopen/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Branch_delete_branch` | `/branch/delete/<int:pk>/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Branch_edit_branch` | `/branch/edit/<int:pk>/` | `popup_form_fragment` | Not audited | Form marker verified where renderable; full audit pending | Fragment is hosted inside the shared popup; no standalone shell |
| `Module_Branch_index_branch` | `/branch/` | `list_page` | Shared ListPage | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Branch_quick_search` | `/branch/quick-search/` | `special_screen` | Not audited | Pending type-specific and responsive audit | — |
| `Module_Branch_switch` | `/branch/switch/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Branch_tree` | `/branch/tree/` | `special_screen` | Not audited | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Center_add` | `/branch/centers/add/` | `popup_form_fragment` | Not audited | Form marker verified where renderable; full audit pending | Fragment is hosted inside the shared popup; no standalone shell |
| `Module_Center_edit` | `/branch/centers/edit/<int:pk>/` | `popup_form_fragment` | Not audited | Form marker verified where renderable; full audit pending | Fragment is hosted inside the shared popup; no standalone shell |
| `Module_Center_list` | `/branch/centers/` | `list_page` | Legacy list | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Collections_reconciliation_list` | `/collections/reconciliation/` | `list_page` | Shared ListPage | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Collections_report_daily` | `/collections/reports/daily/` | `report_page` | Not audited | Shared report title/search bar, reset, permission-gated exports and empty state; cross-browser smoke passed at 390x844, 1024x768 and 1366x768 | — |
| `Module_Collections_report_efficiency` | `/collections/reports/efficiency/` | `report_page` | Not audited | Shared report title/search bar, reset, permission-gated exports and empty state; cross-browser smoke passed at 390x844, 1024x768 and 1366x768 | — |
| `Module_Collections_report_excel` | `/collections/reports/export/excel/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Collections_report_pdf` | `/collections/reports/export/pdf/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Collections_report_performance` | `/collections/reports/performance/` | `report_page` | Not audited | Shared report title/search bar, reset, permission-gated exports and empty state; cross-browser smoke passed at 390x844, 1024x768 and 1366x768 | — |
| `Module_Collections_report_variances` | `/collections/reports/variances/` | `report_page` | Not audited | Shared report title/search bar, reset, permission-gated exports and empty state; cross-browser smoke passed at 390x844, 1024x768 and 1366x768 | — |
| `Module_Collections_sheet_cancel` | `/collections/sheets/<int:pk>/cancel/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Collections_sheet_detail` | `/collections/sheets/<int:pk>/` | `detail_statement_page` | Not audited | Pending type-specific and responsive audit | — |
| `Module_Collections_sheet_entry` | `/collections/sheets/<int:pk>/items/<int:item_pk>/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Collections_sheet_generate` | `/collections/sheets/generate/` | `popup_form_fragment` | Not audited | Form marker verified where renderable; full audit pending | Fragment is hosted inside the shared popup; no standalone shell |
| `Module_Collections_sheet_list` | `/collections/sheets/` | `list_page` | Shared ListPage | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Collections_sheet_post` | `/collections/reconciliation/<int:pk>/post/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Collections_sheet_print` | `/collections/sheets/<int:pk>/print/` | `special_screen` | Not audited | Pending type-specific and responsive audit | Print-specific layout remains unchanged by design |
| `Module_Collections_sheet_reconcile` | `/collections/reconciliation/<int:pk>/reconcile/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Collections_sheet_reversal_approve` | `/collections/reversals/<int:pk>/approve/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Collections_sheet_reversal_request` | `/collections/sheets/<int:pk>/reversal/request/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Collections_sheet_start` | `/collections/sheets/<int:pk>/start/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Collections_sheet_submit` | `/collections/sheets/<int:pk>/submit/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Group_add` | `/branch/groups/add/` | `popup_form_fragment` | Not audited | Form marker verified where renderable; full audit pending | Fragment is hosted inside the shared popup; no standalone shell |
| `Module_Group_edit` | `/branch/groups/edit/<int:pk>/` | `popup_form_fragment` | Not audited | Form marker verified where renderable; full audit pending | Fragment is hosted inside the shared popup; no standalone shell |
| `Module_Group_list` | `/branch/groups/` | `list_page` | Legacy list | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Home_home` | `/` | `dashboard` | Not audited | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Import_approve` | `/imports/approve/<int:pk>/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Import_confirm` | `/imports/confirm/<int:pk>/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Import_errors` | `/imports/errors/<int:pk>/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Import_list` | `/imports/` | `special_screen` | Not audited | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Import_template` | `/imports/template/<str:import_type>/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Import_upload` | `/imports/upload/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Import_validate` | `/imports/validate/<int:pk>/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Loans_application_add` | `/loans/applications/add/` | `popup_form_fragment` | Not audited | Form marker verified where renderable; full audit pending | Fragment is hosted inside the shared popup; no standalone shell |
| `Module_Loans_application_cancel` | `/loans/applications/<int:pk>/cancel/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Loans_application_review` | `/loans/applications/<int:pk>/review/` | `popup_form_fragment` | Not audited | Form marker verified where renderable; full audit pending | Fragment is hosted inside the shared popup; no standalone shell |
| `Module_Loans_application_submit` | `/loans/applications/<int:pk>/submit/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Loans_applications` | `/loans/applications/` | `list_page` | Shared ListPage | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Loans_approval_tier_add` | `/loans/business-rules/approval-tiers/add/` | `popup_form_fragment` | Not audited | Form marker verified where renderable; full audit pending | Fragment is hosted inside the shared popup; no standalone shell |
| `Module_Loans_approval_tier_edit` | `/loans/business-rules/approval-tiers/edit/<int:pk>/` | `popup_form_fragment` | Not audited | Form marker verified where renderable; full audit pending | Fragment is hosted inside the shared popup; no standalone shell |
| `Module_Loans_approval_tiers` | `/loans/business-rules/approval-tiers/` | `list_page` | Shared ListPage | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Loans_classification` | `/loans/classification/` | `report_page` | Not audited | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Loans_classification_excel` | `/loans/classification/export/excel/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Loans_classification_pdf` | `/loans/classification/export/pdf/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Loans_disbursement_add` | `/loans/applications/<int:pk>/disburse/` | `popup_form_fragment` | Not audited | Form marker verified where renderable; full audit pending | Fragment is hosted inside the shared popup; no standalone shell |
| `Module_Loans_disbursements` | `/loans/disbursements/` | `list_page` | Shared ListPage | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Loans_history` | `/loans/<int:pk>/history/` | `detail_statement_page` | Not audited | Pending type-specific and responsive audit | — |
| `Module_Loans_par_bucket_add` | `/loans/business-rules/par-buckets/add/` | `popup_form_fragment` | Not audited | Form marker verified where renderable; full audit pending | Fragment is hosted inside the shared popup; no standalone shell |
| `Module_Loans_par_bucket_edit` | `/loans/business-rules/par-buckets/edit/<int:pk>/` | `popup_form_fragment` | Not audited | Form marker verified where renderable; full audit pending | Fragment is hosted inside the shared popup; no standalone shell |
| `Module_Loans_par_buckets` | `/loans/business-rules/par-buckets/` | `list_page` | Shared ListPage | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Loans_portfolio` | `/loans/portfolio/` | `list_page` | Shared ListPage | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Loans_product_activate` | `/loans/products/<int:pk>/activate/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Loans_product_add` | `/loans/products/add/` | `popup_form_fragment` | Not audited | Form marker verified where renderable; full audit pending | Fragment is hosted inside the shared popup; no standalone shell |
| `Module_Loans_product_deactivate` | `/loans/products/<int:pk>/deactivate/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Loans_product_edit` | `/loans/products/edit/<int:pk>/` | `popup_form_fragment` | Not audited | Form marker verified where renderable; full audit pending | Fragment is hosted inside the shared popup; no standalone shell |
| `Module_Loans_products` | `/loans/products/` | `list_page` | Shared ListPage | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Loans_recovery` | `/loans/<int:pk>/recovery/` | `popup_form_fragment` | Not audited | Form marker verified where renderable; full audit pending | Fragment is hosted inside the shared popup; no standalone shell |
| `Module_Loans_repayment_add` | `/loans/<int:pk>/repay/` | `popup_form_fragment` | Not audited | Form marker verified where renderable; full audit pending | Fragment is hosted inside the shared popup; no standalone shell |
| `Module_Loans_repayments` | `/loans/repayments/` | `list_page` | Shared ListPage | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Loans_reschedule` | `/loans/<int:pk>/reschedule/` | `popup_form_fragment` | Not audited | Form marker verified where renderable; full audit pending | Fragment is hosted inside the shared popup; no standalone shell |
| `Module_Loans_schedule` | `/loans/<int:pk>/schedule/` | `detail_statement_page` | Not audited | Pending type-specific and responsive audit | — |
| `Module_Loans_settle` | `/loans/<int:pk>/settle/` | `popup_form_fragment` | Not audited | Form marker verified where renderable; full audit pending | Fragment is hosted inside the shared popup; no standalone shell |
| `Module_Loans_statement` | `/loans/<int:pk>/statement/` | `detail_statement_page` | Not audited | Pending type-specific and responsive audit | — |
| `Module_Loans_waive_interest` | `/loans/<int:pk>/waive-interest/` | `popup_form_fragment` | Not audited | Form marker verified where renderable; full audit pending | Fragment is hosted inside the shared popup; no standalone shell |
| `Module_Loans_write_off` | `/loans/<int:pk>/write-off/` | `popup_form_fragment` | Not audited | Form marker verified where renderable; full audit pending | Fragment is hosted inside the shared popup; no standalone shell |
| `Module_Members_add` | `/branch/members/add/` | `popup_form_fragment` | Not audited | Form marker verified where renderable; full audit pending | Fragment is hosted inside the shared popup; no standalone shell |
| `Module_Members_detail` | `/branch/members/<int:pk>/` | `detail_statement_page` | Not audited | Pending type-specific and responsive audit | — |
| `Module_Members_edit` | `/branch/members/edit/<int:pk>/` | `popup_form_fragment` | Not audited | Form marker verified where renderable; full audit pending | Fragment is hosted inside the shared popup; no standalone shell |
| `Module_Members_kyc` | `/branch/members/kyc/<int:pk>/` | `special_screen` | Not audited | Pending type-specific and responsive audit | — |
| `Module_Members_kyc_file` | `/branch/members/kyc/file/<int:file_id>/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Members_kyc_verify` | `/branch/members/kyc/verify/<int:document_id>/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Members_list` | `/branch/members/` | `list_page` | Shared ListPage | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Members_photo` | `/branch/members/photo/<int:file_id>/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Members_status` | `/branch/members/status/<int:pk>/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Notifications_list` | `/notifications/` | `list_page` | Legacy list | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Notifications_mark_read` | `/notifications/read/<int:pk>/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Notifications_preferences` | `/notifications/preferences/` | `special_screen` | Not audited | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Notifications_preferences_save` | `/notifications/preferences/save/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_account_list` | `/reports/account-list/` | `report_page` | Not audited | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Reports_account_list_excel` | `/reports/account-list/export/excel/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_account_list_grid` | `/reports/account-list/data/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_account_list_pdf` | `/reports/account-list/export/pdf/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_aging` | `/reports/aging/` | `report_page` | Not audited | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Reports_aging_excel` | `/reports/aging/export/excel/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_aging_grid` | `/reports/aging/data/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_aging_pdf` | `/reports/aging/export/pdf/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_balance_sheet` | `/reports/balance-sheet/` | `report_page` | Not audited | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Reports_balance_sheet_excel` | `/reports/balance-sheet/export/excel/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_balance_sheet_grid` | `/reports/balance-sheet/data/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_balance_sheet_pdf` | `/reports/balance-sheet/export/pdf/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_balance_summary` | `/reports/balance-summary/` | `report_page` | Not audited | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Reports_balance_summary_excel` | `/reports/balance-summary/export/excel/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_balance_summary_grid` | `/reports/balance-summary/data/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_balance_summary_pdf` | `/reports/balance-summary/export/pdf/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_cash_book` | `/reports/cash-book/` | `report_page` | Not audited | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Reports_cash_book_excel` | `/reports/cash-book/export/excel/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_cash_book_grid` | `/reports/cash-book/data/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_cash_book_pdf` | `/reports/cash-book/export/pdf/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_classification` | `/reports/classification/` | `report_page` | Not audited | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Reports_classification_excel` | `/reports/classification/export/excel/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_classification_grid` | `/reports/classification/data/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_classification_pdf` | `/reports/classification/export/pdf/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_collection_efficiency` | `/reports/collection-efficiency/` | `report_page` | Not audited | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Reports_collection_efficiency_excel` | `/reports/collection-efficiency/export/excel/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_collection_efficiency_grid` | `/reports/collection-efficiency/data/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_collection_efficiency_pdf` | `/reports/collection-efficiency/export/pdf/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_collection_register` | `/reports/collection-register/` | `report_page` | Not audited | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Reports_collection_register_excel` | `/reports/collection-register/export/excel/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_collection_register_grid` | `/reports/collection-register/data/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_collection_register_pdf` | `/reports/collection-register/export/pdf/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_collection_summary` | `/reports/collection-summary/` | `report_page` | Not audited | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Reports_collection_summary_excel` | `/reports/collection-summary/export/excel/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_collection_summary_grid` | `/reports/collection-summary/data/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_collection_summary_pdf` | `/reports/collection-summary/export/pdf/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_collector_performance` | `/reports/collector-performance/` | `report_page` | Not audited | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Reports_collector_performance_excel` | `/reports/collector-performance/export/excel/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_collector_performance_grid` | `/reports/collector-performance/data/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_collector_performance_pdf` | `/reports/collector-performance/export/pdf/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_day_reopen_reversals` | `/reports/day-reopen-reversals/` | `report_page` | Not audited | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Reports_day_reopen_reversals_excel` | `/reports/day-reopen-reversals/export/excel/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_day_reopen_reversals_grid` | `/reports/day-reopen-reversals/data/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_day_reopen_reversals_pdf` | `/reports/day-reopen-reversals/export/pdf/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_disbursement_register` | `/reports/disbursement-register/` | `report_page` | Not audited | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Reports_disbursement_register_excel` | `/reports/disbursement-register/export/excel/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_disbursement_register_grid` | `/reports/disbursement-register/data/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_disbursement_register_pdf` | `/reports/disbursement-register/export/pdf/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_dormant_accounts` | `/reports/dormant-accounts/` | `report_page` | Not audited | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Reports_dormant_accounts_excel` | `/reports/dormant-accounts/export/excel/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_dormant_accounts_grid` | `/reports/dormant-accounts/data/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_dormant_accounts_pdf` | `/reports/dormant-accounts/export/pdf/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_failed_logins` | `/reports/failed-logins/` | `report_page` | Not audited | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Reports_failed_logins_excel` | `/reports/failed-logins/export/excel/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_failed_logins_grid` | `/reports/failed-logins/data/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_failed_logins_pdf` | `/reports/failed-logins/export/pdf/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_general_ledger` | `/reports/general-ledger/` | `report_page` | Not audited | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Reports_general_ledger_excel` | `/reports/general-ledger/export/excel/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_general_ledger_grid` | `/reports/general-ledger/data/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_general_ledger_pdf` | `/reports/general-ledger/export/pdf/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_income_statement` | `/reports/income-statement/` | `report_page` | Not audited | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Reports_income_statement_excel` | `/reports/income-statement/export/excel/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_income_statement_grid` | `/reports/income-statement/data/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_income_statement_pdf` | `/reports/income-statement/export/pdf/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_index` | `/reports/` | `report_page` | Not audited | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Reports_interest_posted` | `/reports/interest-posted/` | `report_page` | Not audited | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Reports_interest_posted_excel` | `/reports/interest-posted/export/excel/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_interest_posted_grid` | `/reports/interest-posted/data/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_interest_posted_pdf` | `/reports/interest-posted/export/pdf/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_kyc_completeness` | `/reports/kyc-completeness/` | `report_page` | Not audited | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Reports_kyc_completeness_excel` | `/reports/kyc-completeness/export/excel/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_kyc_completeness_grid` | `/reports/kyc-completeness/data/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_kyc_completeness_pdf` | `/reports/kyc-completeness/export/pdf/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_kyc_pending_expired` | `/reports/kyc-pending-expired/` | `report_page` | Not audited | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Reports_kyc_pending_expired_excel` | `/reports/kyc-pending-expired/export/excel/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_kyc_pending_expired_grid` | `/reports/kyc-pending-expired/data/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_kyc_pending_expired_pdf` | `/reports/kyc-pending-expired/export/pdf/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_loan_statement` | `/reports/loan-statement/` | `report_page` | Not audited | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Reports_loan_statement_excel` | `/reports/loan-statement/export/excel/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_loan_statement_grid` | `/reports/loan-statement/data/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_loan_statement_pdf` | `/reports/loan-statement/export/pdf/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_member_list` | `/reports/member-list/` | `report_page` | Not audited | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Reports_member_list_excel` | `/reports/member-list/export/excel/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_member_list_grid` | `/reports/member-list/data/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_member_list_pdf` | `/reports/member-list/export/pdf/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_member_statement` | `/reports/member-statement/` | `report_page` | Not audited | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Reports_member_statement_excel` | `/reports/member-statement/export/excel/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_member_statement_grid` | `/reports/member-statement/data/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_member_statement_pdf` | `/reports/member-statement/export/pdf/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_new_members` | `/reports/new-members/` | `report_page` | Not audited | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Reports_new_members_excel` | `/reports/new-members/export/excel/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_new_members_grid` | `/reports/new-members/data/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_new_members_pdf` | `/reports/new-members/export/pdf/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_outstanding_loans` | `/reports/outstanding-loans/` | `report_page` | Not audited | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Reports_outstanding_loans_excel` | `/reports/outstanding-loans/export/excel/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_outstanding_loans_grid` | `/reports/outstanding-loans/data/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_outstanding_loans_pdf` | `/reports/outstanding-loans/export/pdf/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_overdue_loans` | `/reports/overdue-loans/` | `report_page` | Not audited | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Reports_overdue_loans_excel` | `/reports/overdue-loans/export/excel/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_overdue_loans_grid` | `/reports/overdue-loans/data/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_overdue_loans_pdf` | `/reports/overdue-loans/export/pdf/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_portfolio_at_risk` | `/reports/portfolio-at-risk/` | `report_page` | Not audited | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Reports_portfolio_at_risk_excel` | `/reports/portfolio-at-risk/export/excel/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_portfolio_at_risk_grid` | `/reports/portfolio-at-risk/data/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_portfolio_at_risk_pdf` | `/reports/portfolio-at-risk/export/pdf/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_privileged_actions` | `/reports/privileged-actions/` | `report_page` | Not audited | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Reports_privileged_actions_excel` | `/reports/privileged-actions/export/excel/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_privileged_actions_grid` | `/reports/privileged-actions/data/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_privileged_actions_pdf` | `/reports/privileged-actions/export/pdf/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_receipts_payments` | `/reports/receipts-payments/` | `report_page` | Not audited | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Reports_receipts_payments_excel` | `/reports/receipts-payments/export/excel/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_receipts_payments_grid` | `/reports/receipts-payments/data/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_receipts_payments_pdf` | `/reports/receipts-payments/export/pdf/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_repayment_schedule` | `/reports/repayment-schedule/` | `report_page` | Not audited | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Reports_repayment_schedule_excel` | `/reports/repayment-schedule/export/excel/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_repayment_schedule_grid` | `/reports/repayment-schedule/data/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_repayment_schedule_pdf` | `/reports/repayment-schedule/export/pdf/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_role_permission_history` | `/reports/role-permission-history/` | `report_page` | Not audited | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Reports_role_permission_history_excel` | `/reports/role-permission-history/export/excel/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_role_permission_history_grid` | `/reports/role-permission-history/data/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_role_permission_history_pdf` | `/reports/role-permission-history/export/pdf/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_shortage_excess` | `/reports/shortage-excess/` | `report_page` | Not audited | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Reports_shortage_excess_excel` | `/reports/shortage-excess/export/excel/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_shortage_excess_grid` | `/reports/shortage-excess/data/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_shortage_excess_pdf` | `/reports/shortage-excess/export/pdf/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_status_summary` | `/reports/status-summary/` | `report_page` | Not audited | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Reports_status_summary_excel` | `/reports/status-summary/export/excel/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_status_summary_grid` | `/reports/status-summary/data/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_status_summary_pdf` | `/reports/status-summary/export/pdf/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_transaction_register` | `/reports/transaction-register/` | `report_page` | Not audited | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Reports_transaction_register_excel` | `/reports/transaction-register/export/excel/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_transaction_register_grid` | `/reports/transaction-register/data/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_transaction_register_pdf` | `/reports/transaction-register/export/pdf/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_trial_balance` | `/reports/trial-balance/` | `report_page` | Not audited | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Reports_trial_balance_excel` | `/reports/trial-balance/export/excel/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_trial_balance_grid` | `/reports/trial-balance/data/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_trial_balance_pdf` | `/reports/trial-balance/export/pdf/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_user_access_review` | `/reports/user-access-review/` | `report_page` | Not audited | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Reports_user_access_review_excel` | `/reports/user-access-review/export/excel/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_user_access_review_grid` | `/reports/user-access-review/data/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_user_access_review_pdf` | `/reports/user-access-review/export/pdf/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_write_offs` | `/reports/write-offs/` | `report_page` | Not audited | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Reports_write_offs_excel` | `/reports/write-offs/export/excel/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_write_offs_grid` | `/reports/write-offs/data/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Reports_write_offs_pdf` | `/reports/write-offs/export/pdf/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Savings_account_add` | `/savings/accounts/add/` | `popup_form_fragment` | Not audited | Form marker verified where renderable; full audit pending | Fragment is hosted inside the shared popup; no standalone shell |
| `Module_Savings_accounts` | `/savings/accounts/` | `list_page` | Shared ListPage | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Savings_approve_withdrawal` | `/savings/transactions/<int:pk>/approve/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Savings_balance_report` | `/savings/reports/balances/` | `report_page` | Not audited | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | Aggregate by branch/product; not a record-list grid |
| `Module_Savings_close_account` | `/savings/accounts/<int:pk>/close/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Savings_deposit` | `/savings/transactions/deposit/` | `popup_form_fragment` | Not audited | Form marker verified where renderable; full audit pending | Fragment is hosted inside the shared popup; no standalone shell |
| `Module_Savings_fee` | `/savings/transactions/fee/` | `popup_form_fragment` | Not audited | Form marker verified where renderable; full audit pending | Fragment is hosted inside the shared popup; no standalone shell |
| `Module_Savings_interest` | `/savings/transactions/interest/` | `popup_form_fragment` | Not audited | Form marker verified where renderable; full audit pending | Fragment is hosted inside the shared popup; no standalone shell |
| `Module_Savings_product_activate` | `/savings/products/<int:pk>/activate/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Savings_product_add` | `/savings/products/add/` | `popup_form_fragment` | Not audited | Form marker verified where renderable; full audit pending | Fragment is hosted inside the shared popup; no standalone shell |
| `Module_Savings_product_deactivate` | `/savings/products/<int:pk>/deactivate/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Savings_product_edit` | `/savings/products/edit/<int:pk>/` | `popup_form_fragment` | Not audited | Form marker verified where renderable; full audit pending | Fragment is hosted inside the shared popup; no standalone shell |
| `Module_Savings_products` | `/savings/products/` | `list_page` | Shared ListPage | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Savings_reactivate_account` | `/savings/accounts/<int:pk>/reactivate/submit/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Savings_reactivation_form` | `/savings/accounts/<int:pk>/reactivate/` | `popup_form_fragment` | Not audited | Form marker verified where renderable; full audit pending | Fragment is hosted inside the shared popup; no standalone shell |
| `Module_Savings_reconciliation` | `/savings/reports/reconciliation/` | `report_page` | Not audited | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768; type-specific convention verification pending | Single date-keyed reconciliation snapshot; not a record-list grid |
| `Module_Savings_reject_withdrawal` | `/savings/transactions/<int:pk>/reject/post/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Savings_rejection_form` | `/savings/transactions/<int:pk>/reject/` | `popup_form_fragment` | Not audited | Form marker verified where renderable; full audit pending | Fragment is hosted inside the shared popup; no standalone shell |
| `Module_Savings_reversal_form` | `/savings/transactions/<int:pk>/reverse/` | `popup_form_fragment` | Not audited | Form marker verified where renderable; full audit pending | Fragment is hosted inside the shared popup; no standalone shell |
| `Module_Savings_reverse` | `/savings/transactions/<int:pk>/reverse/post/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Savings_statement` | `/savings/accounts/<int:pk>/statement/` | `detail_statement_page` | Not audited | Pending type-specific and responsive audit | — |
| `Module_Savings_statement_export` | `/savings/accounts/<int:pk>/statement.csv` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Savings_submit_deposit` | `/savings/transactions/deposit/post/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Savings_submit_fee` | `/savings/transactions/fee/post/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Savings_submit_interest` | `/savings/transactions/interest/post/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Savings_submit_withdraw` | `/savings/transactions/withdraw/post/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Savings_transactions` | `/savings/transactions/` | `list_page` | Shared ListPage | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Savings_withdraw` | `/savings/transactions/withdraw/` | `popup_form_fragment` | Not audited | Form marker verified where renderable; full audit pending | Fragment is hosted inside the shared popup; no standalone shell |
| `Module_Settings_business_rules` | `/settings/business-rules/` | `special_screen` | Not audited | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Settings_business_rules_save` | `/settings/business-rules/save/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Settings_index` | `/settings/` | `special_screen` | Not audited | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Settings_notification_schedule_save` | `/settings/notifications/schedule/save/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Settings_notification_template_save` | `/settings/notifications/templates/save/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Settings_notification_templates` | `/settings/notifications/templates/` | `special_screen` | Not audited | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Settings_organization` | `/settings/organization/` | `special_screen` | Not audited | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Settings_organization_logo` | `/settings/organization/logo/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Settings_organization_save` | `/settings/organization/save/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Settings_preferences` | `/settings/preferences/` | `special_screen` | Not audited | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Settings_preferences_save` | `/settings/preferences/save/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Settings_system` | `/settings/system/` | `special_screen` | Not audited | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `Module_Settings_system_logo` | `/settings/system/logo/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Settings_system_save` | `/settings/system/save/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `Module_Staff_add` | `/branch/staff/add/` | `popup_form_fragment` | Not audited | Form marker verified where renderable; full audit pending | Fragment is hosted inside the shared popup; no standalone shell |
| `Module_Staff_edit` | `/branch/staff/edit/<int:pk>/` | `popup_form_fragment` | Not audited | Form marker verified where renderable; full audit pending | Fragment is hosted inside the shared popup; no standalone shell |
| `Module_Staff_list` | `/branch/staff/` | `list_page` | Legacy list | Cross-browser smoke passed (Chromium, Firefox, WebKit) at 390x844, 1024x768 and 1366x768 | — |
| `favicon` | `/favicon.ico` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |
| `health` | `/health/` | `non_page` | N/A | N/A | Non-page endpoint (JSON, download, or action) |

## Regression commands

Run route classification, ListPage-template and HTML marker checks with:

```sh
python manage.py test core.common.tests.UIConventionRegistryTests core.common.tests.UIConventionRenderTests --keepdb
```

Run the route-wide Playwright responsive audit with:

```sh
npx playwright install --with-deps
python manage.py test e2e.responsive_audit.ResponsiveAuditTests.test_registered_routes_across_responsive_matrix --keepdb
```

The responsive audit covers routes that resolve to an allowed GET and return HTML 200 for a sample request. Object-specific edit, detail, and statement routes need seeded records to be visually tested; their sample-ID limitation is a documented gap, not an exemption from the convention.
