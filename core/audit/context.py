from contextvars import ContextVar
from uuid import uuid4

audit_context_var = ContextVar('audit_context', default=None)


def build_audit_context(request):
    return {
        'user': request.user if request.user.is_authenticated else None,
        'branch_id': getattr(request, 'active_branch_id', None),
        'ip_address': request.META.get('REMOTE_ADDR') or None,
        'user_agent': request.META.get('HTTP_USER_AGENT', '')[:500],
        'correlation_id': uuid4().hex,
    }
