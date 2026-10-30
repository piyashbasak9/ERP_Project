from core.accounts.models import Permission

from .services import get_organization_configuration, get_system_configuration


def organization_context(request):
    allowed_routes = set()
    if request.user.is_authenticated:
        if request.user.is_superuser:
            allowed_routes = {
                "Module_Settings_system_logo",
                "Module_Settings_organization_logo",
            }
        else:
            allowed_routes = set(
                Permission.objects.filter(
                    role_permissions__role__user_roles__user=request.user,
                    is_allowed=True,
                    is_active=True,
                    route_name__in=[
                        "Module_Settings_system_logo",
                        "Module_Settings_organization_logo",
                    ],
                ).values_list("route_name", flat=True)
            )
    return {
        "system_configuration": get_system_configuration(),
        "organization_configuration": get_organization_configuration(),
        "user_preference": getattr(request, "user_preference", None),
        "can_view_system_logo": "Module_Settings_system_logo" in allowed_routes,
        "can_view_organization_logo": (
            "Module_Settings_organization_logo" in allowed_routes
        ),
    }
