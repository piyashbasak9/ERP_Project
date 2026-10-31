from django.urls import path

from . import views

app_name = "notifications"

urlpatterns = [
    path("", views.notification_list, name="Module_Notifications_list"),
    path("preferences/", views.preferences, name="Module_Notifications_preferences"),
    path(
        "preferences/save/",
        views.save_preferences,
        name="Module_Notifications_preferences_save",
    ),
    path("read/<int:pk>/", views.mark_read, name="Module_Notifications_mark_read"),
]
