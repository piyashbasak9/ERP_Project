from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.http import JsonResponse
from django.urls import Resolver404, resolve
from django.utils.http import url_has_allowed_host_and_scheme

from core.common.popup import popup_json_response

PUBLIC_ROUTE_NAMES = {
    'Module_Auth_login',
    'health',
}


class GlobalLoginRequiredMiddleware:
    """Redirect anonymous users to login for all non-exempt paths."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.exempt_paths = getattr(settings, 'EXEMPT_FROM_LOGIN', ['/static/'])
        self.login_url = getattr(settings, 'LOGIN_URL', '/accounts/login/')

    def __call__(self, request):
        try:
            route_name = resolve(request.path_info).url_name
        except Resolver404:
            route_name = None

        is_public_route = route_name in PUBLIC_ROUTE_NAMES
        is_static_path = any(request.path_info.startswith(prefix) for prefix in self.exempt_paths)

        if not request.user.is_authenticated and not is_public_route and not is_static_path:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                response = popup_json_response(
                    request,
                    message='Your session has expired. Please sign in again.',
                    status=401,
                )
                if response is not None:
                    return response
                return JsonResponse({
                    'success': False,
                    'message': 'Your session has expired. Please sign in again.',
                    'data': None,
                    'errors': None,
                }, status=401)

            next_url = request.get_full_path()
            if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
                next_url = '/'
            return redirect_to_login(next_url, login_url=self.login_url)

        return self.get_response(request)
