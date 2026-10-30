from django.shortcuts import render
from django.urls import Resolver404, resolve

from core.common.popup import popup_json_response

from .models import UserRole

PUBLIC_ROUTE_NAMES = {'Module_Auth_login', 'health'}
AUTHENTICATED_ONLY_ROUTE_NAMES = {
    'Module_Home_home',
    'Module_Auth_logout',
    'Module_Branch_switch',
}


class URLPermissionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path_info.startswith('/static/'):
            return self.get_response(request)

        try:
            route_name = resolve(request.path_info).url_name
        except Resolver404:
            return self.get_response(request)

        if route_name in PUBLIC_ROUTE_NAMES:
            return self.get_response(request)

        if route_name in AUTHENTICATED_ONLY_ROUTE_NAMES:
            if request.user.is_authenticated and request.user.is_active:
                return self.get_response(request)
            response = popup_json_response(
                request,
                message='You do not have permission to do that.',
                status=403,
            )
            if response is not None:
                return response
            return render(request, 'access_denied.html', {'message': 'Authentication is required.'}, status=403)

        if not request.user.is_authenticated or not request.user.is_active:
            response = popup_json_response(
                request,
                message='You do not have permission to do that.',
                status=403,
            )
            if response is not None:
                return response
            return render(request, 'access_denied.html', {'message': 'Authentication is required.'}, status=403)

        if request.user.is_superuser:
            return self.get_response(request)

        if not route_name:
            response = popup_json_response(
                request,
                message='You do not have permission to do that.',
                status=403,
            )
            if response is not None:
                return response
            return render(request, 'access_denied.html', {
                'message': 'This route is not classified.',
            }, status=403)

        try:
            user_role = UserRole.objects.select_related('role').get(user=request.user)
        except UserRole.DoesNotExist:
            response = popup_json_response(
                request,
                message='You do not have permission to do that.',
                status=403,
            )
            if response is not None:
                return response
            return render(request, 'access_denied.html', {
                'message': "You don't have a role assigned.",
            }, status=403)

        allowed_routes = user_role.role.permissions.filter(
            is_allowed=True,
            is_active=True,
            route_name=route_name,
        ).exists()
        if allowed_routes:
            return self.get_response(request)

        response = popup_json_response(
            request,
            message='You do not have permission to do that.',
            status=403,
        )
        if response is not None:
            return response
        return render(request, 'access_denied.html', {
            'message': 'Access Denied: This route is not allowed.',
        }, status=403)
