import logging
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
logger = logging.getLogger(__name__)
AUTHENTICATED_ONLY_ROUTE_NAMES = {
    'Module_Home_home',
    'Module_Auth_logout',
    'Module_Auth_change_password',
    'Module_Auth_change_password_done',
    'Module_Branch_switch',
    'Module_Branch_quick_search',
}


class URLPermissionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    @staticmethod
    def _deny(request, route_name, missing_permission, message):
        username = (
            request.user.get_username()
            if request.user.is_authenticated
            else 'anonymous'
        )
        if settings.DEBUG:
            logger.warning(
                'Permission denied route=%s user=%s missing_permission=%s',
                route_name or 'unclassified',
                username,
                missing_permission,
            )
            if (
                request.headers.get('x-requested-with') == 'XMLHttpRequest'
                or 'application/json' in request.headers.get('accept', '')
            ):
                return JsonResponse({
                    'success': False,
                    'message': message,
                    'data': None,
                    'errors': None,
                    'request_id': getattr(request, 'request_id', None),
                    'debug': {
                        'type': 'PermissionDenied',
                        'message': missing_permission,
                    },
                }, status=403)
        response = popup_json_response(
            request,
            message='You do not have permission to do that.',
            status=403,
            debug=(
                {'type': 'PermissionDenied', 'message': missing_permission}
                if settings.DEBUG
                else None
            ),
        )
        if response is not None:
            return response
        return render(request, 'access_denied.html', {'message': message}, status=403)

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
            return self._deny(
                request,
                route_name,
                'authenticated active user required',
                'Authentication is required.',
            )

        if not request.user.is_authenticated or not request.user.is_active:
            return self._deny(
                request,
                route_name,
                'authenticated active user required',
                'Authentication is required.',
            )

        if request.user.is_superuser:
            return self.get_response(request)

        if not route_name:
            return self._deny(
                request,
                'unclassified',
                'route classification required',
                'This route is not classified.',
            )

        try:
            user_role = UserRole.objects.select_related('role').get(user=request.user)
        except UserRole.DoesNotExist:
            return self._deny(
                request,
                route_name,
                route_name,
                "You don't have a role assigned.",
            )

        allowed_routes = user_role.role.permissions.filter(
            is_allowed=True,
            is_active=True,
            route_name=route_name,
        ).exists()
        if allowed_routes:
            return self.get_response(request)

        return self._deny(
            request,
            route_name,
            route_name,
            'Access Denied: This route is not allowed.',
        )


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
