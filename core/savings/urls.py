from django.urls import path

from . import views

app_name = 'savings'

urlpatterns = [
    path('products/', views.product_list, name='Module_Savings_products'),
    path('products/add/', views.product_form, name='Module_Savings_product_add'),
    path('products/edit/<int:pk>/', views.product_form, name='Module_Savings_product_edit'),
    path('products/<int:pk>/activate/', views.product_activate, name='Module_Savings_product_activate'),
    path('products/<int:pk>/deactivate/', views.product_deactivate, name='Module_Savings_product_deactivate'),
    path('accounts/', views.account_list, name='Module_Savings_accounts'),
    path('accounts/add/', views.account_create, name='Module_Savings_account_add'),
    path('accounts/<int:pk>/close/', views.close_account, name='Module_Savings_close_account'),
    path('accounts/<int:pk>/statement/', views.statement, name='Module_Savings_statement'),
    path('accounts/<int:pk>/statement.csv', views.statement_export, name='Module_Savings_statement_export'),
    path('accounts/<int:pk>/reactivate/', views.reactivation_form, name='Module_Savings_reactivation_form'),
    path('accounts/<int:pk>/reactivate/submit/', views.reactivate_account, name='Module_Savings_reactivate_account'),
    path('reports/balances/', views.balance_report, name='Module_Savings_balance_report'),
    path('reports/reconciliation/', views.reconciliation_report, name='Module_Savings_reconciliation'),
    path('transactions/', views.transaction_list, name='Module_Savings_transactions'),
    path('transactions/deposit/', views.transaction_create, {'operation': 'deposit'}, name='Module_Savings_deposit'),
    path('transactions/deposit/post/', views.transaction_submit, {'operation': 'deposit'}, name='Module_Savings_submit_deposit'),
    path('transactions/withdraw/', views.transaction_create, {'operation': 'withdraw'}, name='Module_Savings_withdraw'),
    path('transactions/withdraw/post/', views.transaction_submit, {'operation': 'withdraw'}, name='Module_Savings_submit_withdraw'),
    path('transactions/fee/', views.charge_fee, name='Module_Savings_fee'),
    path('transactions/fee/post/', views.charge_fee_submit, name='Module_Savings_submit_fee'),
    path('transactions/interest/', views.interest_post, name='Module_Savings_interest'),
    path('transactions/interest/post/', views.interest_post_submit, name='Module_Savings_submit_interest'),
    path('transactions/<int:pk>/approve/', views.approve_withdrawal, name='Module_Savings_approve_withdrawal'),
    path('transactions/<int:pk>/reject/', views.rejection_form, name='Module_Savings_rejection_form'),
    path('transactions/<int:pk>/reject/post/', views.reject_withdrawal, name='Module_Savings_reject_withdrawal'),
    path('transactions/<int:pk>/reverse/', views.reversal_form, name='Module_Savings_reversal_form'),
    path('transactions/<int:pk>/reverse/post/', views.reverse_transaction, name='Module_Savings_reverse'),
]
