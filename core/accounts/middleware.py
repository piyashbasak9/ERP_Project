import time

from django.conf import settings
from django.contrib.auth import logout
from django.contrib.auth.views import redirect_to_login
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import Resolver404, resolve
from django.utils.http import urlencode

from core.common.popup import popup_json_response

from .models import UserRole

PUBLIC_ROUTE_NAMES = {'Module_Auth_login', 'favicon', 'health'}
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


class AbsoluteSessionExpiryMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            now = int(time.time())
            started_at = request.session.get('auth_started_at')
            if started_at is None:
                request.session['auth_started_at'] = now
            else:
                lifetime = int(getattr(settings, 'SESSION_ABSOLUTE_TIMEOUT_HOURS', 12)) * 3600
                if now - int(started_at) >= lifetime:
                    logout(request)
                    accepts_json = 'application/json' in request.headers.get('accept', '')
                    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or accepts_json:
                        return JsonResponse(
                            {
                                'success': False,
                                'message': 'Your session has expired. Please sign in again.',
                                'login_url': (
                                    f'{settings.LOGIN_URL}?'
                                    f'{urlencode({"next": request.get_full_path()})}'
                                ),
                            },
                            status=401,
                        )
                    return redirect_to_login(request.get_full_path(), settings.LOGIN_URL)
        return self.get_response(request)
