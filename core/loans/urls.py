from django.urls import path

from . import views

app_name = "loans"

urlpatterns = [
    path("products/", views.product_list, name="Module_Loans_products"),
    path("products/add/", views.product_form, name="Module_Loans_product_add"),
    path("products/edit/<int:pk>/", views.product_form, name="Module_Loans_product_edit"),
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
