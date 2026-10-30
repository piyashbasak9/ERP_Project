from django.urls import path

from core.reports.views import report_view

from . import views

app_name = 'accounting'

urlpatterns = [
    path('accounts/', views.account_list, name='Module_Accounting_account_list'),
    path('accounts/add/', views.account_form, name='Module_Accounting_account_add'),
    path('accounts/edit/<int:pk>/', views.account_form, name='Module_Accounting_account_edit'),
    path('fiscal-years/', views.fiscal_year_list, name='Module_Accounting_fiscal_years'),
    path('fiscal-years/add/', views.fiscal_year_form, name='Module_Accounting_fiscal_year_add'),
    path('periods/add/', views.period_form, name='Module_Accounting_period_add'),
    path('periods/<int:pk>/close/', views.close_period, name='Module_Accounting_period_close'),
    path('system-accounts/', views.system_account_list, name='Module_Accounting_system_accounts'),
    path('system-accounts/add/', views.system_account_form, name='Module_Accounting_system_account_add'),
    path('system-accounts/<int:pk>/', views.system_account_form, name='Module_Accounting_system_account_edit'),
    path('journal-entries/', views.journal_entry_list, name='Module_Accounting_journal_list'),
    path('journal-entries/add/', views.journal_entry_create, name='Module_Accounting_journal_add'),
    path('journal-entries/<int:pk>/', views.journal_entry_detail, name='Module_Accounting_journal_detail'),
    path('journal-entries/<int:pk>/post/', views.journal_entry_post, name='Module_Accounting_journal_post'),
    path('journal-entries/<int:pk>/reverse/', views.journal_entry_reverse, name='Module_Accounting_journal_reverse'),
    path(
        'trial-balance/',
        report_view,
        {'report_slug': 'trial-balance'},
        name='Module_Accounting_trial_balance',
    ),
    path('reconciliation/', views.reconciliation_list, name='Module_Accounting_reconciliation_list'),
    path('reconciliation/add/', views.reconciliation_create, name='Module_Accounting_reconciliation_add'),
    path('reconciliation/<int:pk>/confirm/', views.reconciliation_confirm, name='Module_Accounting_reconciliation_confirm'),
]
