from django.urls import path

from . import views

app_name = 'audit'

urlpatterns = [
    path('logs/', views.logs, name='Module_Audit_logs'),
    path(
        "trail/<str:entity>/<str:entity_id>/",
        views.trail,
        name="Module_Audit_trail",
    ),
    path("events/", views.events, name="Module_Audit_events"),
    path("dashboard/", views.dashboard, name="Module_Audit_dashboard"),
]
