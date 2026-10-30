from django.db import transaction

from .context import audit_context_var, build_audit_context
from .services import log_action, record_system_event


class AuditContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        context = build_audit_context(request)
        token = audit_context_var.set(context)
        try:
            try:
                with transaction.atomic():
                    response = self.get_response(request)
                    route_name = getattr(
                        getattr(request, "resolver_match", None), "url_name", ""
                    )
                    if request.method == "POST" and response.status_code < 400:
                        log_action(
                            "RequestMutation",
                            "HTTPMutation",
                            route_name,
                            new_values={"route_name": route_name, "status": response.status_code},
                        )
                    if (
                        request.method not in {"GET", "HEAD", "OPTIONS"}
                        and response.status_code >= 400
                    ):
                        transaction.set_rollback(True)
            except Exception as error:
                record_system_event(
                    category="error",
                    severity="error",
                    message=f"Unhandled {type(error).__name__} in "
                    f"{getattr(getattr(request, 'resolver_match', None), 'url_name', '')}",
                )
                raise
            if response.status_code >= 500:
                record_system_event(
                    category="error",
                    severity="error",
                    message=f"HTTP {response.status_code} on "
                    f"{getattr(getattr(request, 'resolver_match', None), 'url_name', '')}",
                )
            response['X-Request-ID'] = context['correlation_id']
            return response
        finally:
            audit_context_var.reset(token)
