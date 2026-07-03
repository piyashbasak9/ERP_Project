from django.shortcuts import redirect
from django.urls import reverse
from django.conf import settings

class GlobalLoginRequiredMiddleware:
    """
    Redirect anonymous users to login for all non-exempt paths.
    Exempt paths are taken from `settings.EXEMPT_FROM_LOGIN`.
    """
    def __init__(self, get_response):
        self.get_response = get_response
        self.exempt_paths = getattr(settings, 'EXEMPT_FROM_LOGIN', [
            '/accounts/login/',
            '/accounts/logout/',
            '/static/',
            '/media/',
        ])
        self.login_url = getattr(settings, 'LOGIN_URL', '/accounts/login/')

    def __call__(self, request):
        # allow admin login pages and built-in auth paths if present
        path = request.path
        is_exempt = any(path.startswith(p) for p in self.exempt_paths)

        if not request.user.is_authenticated and not is_exempt:
            return redirect(f"{self.login_url}?next={path}")

        return self.get_response(request)
