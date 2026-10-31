"""
URL configuration for ERP project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path

from ERP.views import health, home

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', home, name='Module_Home_home'),
    path('health/', health, name='health'),
    path("accounts/", include("core.accounts.urls")),
    path("branch/", include("core.branch.urls")),
    path("audit/", include("core.audit.urls")),
    path("accounting/", include("core.accounting.urls")),
    path("savings/", include("core.savings.urls")),
    path("loans/", include("core.loans.urls")),
    path("collections/", include("core.collections.urls")),
    path("reports/", include("core.reports.urls")),
    path("settings/", include("core.configuration.urls")),
    path("notifications/", include("core.notifications.urls")),
    path("imports/", include("core.bulk_imports.urls")),
]
