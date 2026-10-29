from django.urls import path

from . import views

app_name = 'audit'

urlpatterns = [
    path('logs/', views.logs, name='Module_Audit_logs'),
]
