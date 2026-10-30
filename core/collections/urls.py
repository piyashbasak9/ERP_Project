from django.urls import path

from core.reports.views import report_excel, report_pdf, report_view

from . import views

app_name = "collections"

urlpatterns = [
    path("sheets/", views.sheet_list, name="Module_Collections_sheet_list"),
    path(
        "sheets/generate/",
        views.sheet_generate,
        name="Module_Collections_sheet_generate",
    ),
    path(
        "sheets/<int:pk>/",
        views.sheet_detail,
        name="Module_Collections_sheet_detail",
    ),
    path(
        "sheets/<int:pk>/start/",
        views.sheet_start,
        name="Module_Collections_sheet_start",
    ),
    path(
        "sheets/<int:pk>/items/<int:item_pk>/",
        views.sheet_entry,
        name="Module_Collections_sheet_entry",
    ),
    path(
        "sheets/<int:pk>/submit/",
        views.sheet_submit,
        name="Module_Collections_sheet_submit",
    ),
    path(
        "sheets/<int:pk>/cancel/",
        views.sheet_cancel,
        name="Module_Collections_sheet_cancel",
    ),
    path(
        "sheets/<int:pk>/reversal/request/",
        views.sheet_reversal_request,
        name="Module_Collections_sheet_reversal_request",
    ),
    path(
        "reversals/<int:pk>/approve/",
        views.sheet_reversal_approve,
        name="Module_Collections_sheet_reversal_approve",
    ),
    path(
        "sheets/<int:pk>/print/",
        views.sheet_print,
        name="Module_Collections_sheet_print",
    ),
    path(
        "reconciliation/",
        views.reconciliation_list,
        name="Module_Collections_reconciliation_list",
    ),
    path(
        "reconciliation/<int:pk>/reconcile/",
        views.sheet_reconcile,
        name="Module_Collections_sheet_reconcile",
    ),
    path(
        "reconciliation/<int:pk>/post/",
        views.sheet_post,
        name="Module_Collections_sheet_post",
    ),
    path(
        "reports/daily/",
        report_view,
        {"report_slug": "collection-summary"},
        name="Module_Collections_report_daily",
    ),
    path(
        "reports/performance/",
        report_view,
        {"report_slug": "collector-performance"},
        name="Module_Collections_report_performance",
    ),
    path(
        "reports/efficiency/",
        report_view,
        {"report_slug": "collection-efficiency"},
        name="Module_Collections_report_efficiency",
    ),
    path(
        "reports/variances/",
        report_view,
        {"report_slug": "shortage-excess"},
        name="Module_Collections_report_variances",
    ),
    path(
        "reports/export/excel/",
        report_excel,
        {"report_slug": "collection-register"},
        name="Module_Collections_report_excel",
    ),
    path(
        "reports/export/pdf/",
        report_pdf,
        {"report_slug": "collection-register"},
        name="Module_Collections_report_pdf",
    ),
]
