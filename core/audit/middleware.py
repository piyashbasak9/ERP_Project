from .context import audit_context_var, build_audit_context


class AuditContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        context = build_audit_context(request)
        token = audit_context_var.set(context)
        try:
            response = self.get_response(request)
            response['X-Request-ID'] = context['correlation_id']
            return response
        finally:
            audit_context_var.reset(token)
