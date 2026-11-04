"""Development diagnostics for errors normally rendered by Django."""

import logging

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.urls import Resolver404, resolve
from django.views.csrf import csrf_failure as django_csrf_failure

logger = logging.getLogger(__name__)


def _route_name(request):
    try:
        return resolve(request.path_info).url_name or "unclassified"
    except Resolver404:
        return "unresolved"


class DevelopmentErrorLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if not settings.DEBUG:
            return None

        route_name = _route_name(request)
        user = getattr(request, "user", None)
        username = user.get_username() if user and user.is_authenticated else "anonymous"
        logger.error(
            "Unhandled exception route=%s user=%s",
            route_name,
            username,
            exc_info=(type(exception), exception, exception.__traceback__),
        )
        if isinstance(exception, PermissionDenied):
            logger.warning(
                "Permission denied route=%s user=%s missing_permission=%s",
                route_name,
                username,
                route_name,
            )

        if (
            request.headers.get("x-requested-with") == "XMLHttpRequest"
            or "application/json" in request.headers.get("accept", "")
        ):
            request_id = getattr(request, "request_id", None)
            return JsonResponse(
                {
                    "success": False,
                    "message": "An unexpected error occurred.",
                    "data": None,
                    "errors": None,
                    "request_id": request_id,
                    "debug": {
                        "type": type(exception).__name__,
                        "message": str(exception),
                    },
                },
                status=500,
            )
        return None


def csrf_failure(request, reason=""):
    if settings.DEBUG:
        logger.warning(
            "CSRF verification failed route=%s reason=%s",
            _route_name(request),
            reason,
        )
        if (
            request.headers.get("x-requested-with") == "XMLHttpRequest"
            or "application/json" in request.headers.get("accept", "")
        ):
            return JsonResponse(
                {
                    "success": False,
                    "message": "CSRF verification failed.",
                    "data": None,
                    "errors": None,
                    "request_id": getattr(request, "request_id", None),
                    "debug": {"type": "CSRFError", "message": reason},
                },
                status=403,
            )
    return django_csrf_failure(request, reason=reason)
