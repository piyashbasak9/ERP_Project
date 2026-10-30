from django.urls import path

from . import views

app_name = "loans"

urlpatterns = [
    path("products/", views.product_list, name="Module_Loans_products"),
    path("products/add/", views.product_form, name="Module_Loans_product_add"),
    path("products/edit/<int:pk>/", views.product_form, name="Module_Loans_product_edit"),
    path(
        "products/<int:pk>/activate/",
        views.product_activate,
        name="Module_Loans_product_activate",
    ),
    path(
        "products/<int:pk>/deactivate/",
        views.product_deactivate,
        name="Module_Loans_product_deactivate",
    ),
    path(
        "business-rules/approval-tiers/",
        views.approval_tier_list,
        name="Module_Loans_approval_tiers",
    ),
    path(
        "business-rules/approval-tiers/add/",
        views.approval_tier_form,
        name="Module_Loans_approval_tier_add",
    ),
    path(
        "business-rules/approval-tiers/edit/<int:pk>/",
        views.approval_tier_form,
        name="Module_Loans_approval_tier_edit",
    ),
    path(
        "business-rules/par-buckets/",
        views.par_bucket_list,
        name="Module_Loans_par_buckets",
    ),
    path(
        "business-rules/par-buckets/add/",
        views.par_bucket_form,
        name="Module_Loans_par_bucket_add",
    ),
    path(
        "business-rules/par-buckets/edit/<int:pk>/",
        views.par_bucket_form,
        name="Module_Loans_par_bucket_edit",
    ),
    path(
        "classification/",
        views.classification_report,
        name="Module_Loans_classification",
    ),
    path(
        "classification/export/excel/",
        views.classification_export_excel,
        name="Module_Loans_classification_excel",
    ),
    path(
        "classification/export/pdf/",
        views.classification_export_pdf,
        name="Module_Loans_classification_pdf",
    ),
    path("applications/", views.application_list, name="Module_Loans_applications"),
    path("applications/add/", views.application_create, name="Module_Loans_application_add"),
    path(
        "applications/<int:pk>/submit/",
        views.application_submit,
        name="Module_Loans_application_submit",
    ),
    path(
        "applications/<int:pk>/review/",
        views.application_review,
        name="Module_Loans_application_review",
    ),
    path(
        "applications/<int:pk>/cancel/",
        views.cancel_application,
        name="Module_Loans_application_cancel",
    ),
    path(
        "applications/<int:pk>/disburse/",
        views.disbursement_form,
        name="Module_Loans_disbursement_add",
    ),
    path("disbursements/", views.disbursement_list, name="Module_Loans_disbursements"),
    path("portfolio/", views.portfolio, name="Module_Loans_portfolio"),
    path("repayments/", views.repayment_list, name="Module_Loans_repayments"),
    path(
        "<int:pk>/repay/",
        views.repayment_form,
        name="Module_Loans_repayment_add",
    ),
    path(
        "<int:pk>/schedule/",
        views.schedule,
        name="Module_Loans_schedule",
    ),
    path(
        "<int:pk>/statement/",
        views.loan_statement,
        name="Module_Loans_statement",
    ),
    path(
        "<int:pk>/history/",
        views.loan_history,
        name="Module_Loans_history",
    ),
    path(
        "<int:pk>/reschedule/",
        views.reschedule_form,
        name="Module_Loans_reschedule",
    ),
    path(
        "<int:pk>/settle/",
        views.settlement_form,
        name="Module_Loans_settle",
    ),
    path(
        "<int:pk>/waive-interest/",
        views.settlement_form,
        name="Module_Loans_waive_interest",
    ),
    path(
        "<int:pk>/write-off/",
        views.write_off_form,
        name="Module_Loans_write_off",
    ),
    path(
        "<int:pk>/recovery/",
        views.recovery_form,
        name="Module_Loans_recovery",
    ),
]
