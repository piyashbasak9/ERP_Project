from django.urls import path

from . import views

app_name = "bulk_imports"

urlpatterns = [
    path("", views.import_home, name="Module_Import_list"),
    path("upload/", views.import_upload, name="Module_Import_upload"),
    path(
        "validate/<int:pk>/",
        views.import_validate,
        name="Module_Import_validate",
    ),
    path(
        "errors/<int:pk>/",
        views.import_errors,
        name="Module_Import_errors",
    ),
    path(
        "confirm/<int:pk>/",
        views.import_confirm,
        name="Module_Import_confirm",
    ),
    path(
        "approve/<int:pk>/",
        views.import_approve,
        name="Module_Import_approve",
    ),
    path(
        "template/<str:import_type>/",
        views.import_template,
        name="Module_Import_template",
    ),
]
