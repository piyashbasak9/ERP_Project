from django.urls import path

from .views import report_index, report_route_patterns

app_name = "reports"

urlpatterns = [
    path("", report_index, name="Module_Reports_index"),
    *report_route_patterns(),
]
