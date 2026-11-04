from django.urls import path


def unhandled_exception_view(request):
    raise ValueError("unhandled development view failure")


urlpatterns = [path("health/", unhandled_exception_view, name="health")]
