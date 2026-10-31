from django.urls import path

from core.notifications import views as notification_views

from . import views

app_name = "configuration"

urlpatterns = [
    path("", views.index, name="Module_Settings_index"),
    path("system/", views.system_configuration, name="Module_Settings_system"),
    path("system/logo/", views.system_logo, name="Module_Settings_system_logo"),
    path(
        "system/save/",
        views.save_system_configuration,
        name="Module_Settings_system_save",
    ),
    path(
        "organization/",
        views.organization_configuration,
        name="Module_Settings_organization",
    ),
    path(
        "organization/save/",
        views.save_organization_configuration,
        name="Module_Settings_organization_save",
    ),
    path(
        "organization/logo/",
        views.organization_logo,
        name="Module_Settings_organization_logo",
    ),
    path(
        "preferences/",
        views.user_preferences,
        name="Module_Settings_preferences",
    ),
    path(
        "preferences/save/",
        views.save_user_preferences,
        name="Module_Settings_preferences_save",
    ),
    path(
        "business-rules/",
        views.business_rules,
        name="Module_Settings_business_rules",
    ),
    path(
        "business-rules/save/",
        views.save_business_rules,
        name="Module_Settings_business_rules_save",
    ),
    path(
        "notifications/templates/",
        notification_views.settings_templates,
        name="Module_Settings_notification_templates",
    ),
    path(
        "notifications/templates/save/",
        notification_views.save_settings_template,
        name="Module_Settings_notification_template_save",
    ),
    path(
        "notifications/schedule/save/",
        notification_views.save_settings_configuration,
        name="Module_Settings_notification_schedule_save",
    ),
]
