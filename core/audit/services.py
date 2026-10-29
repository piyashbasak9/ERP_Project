from core.accounts.models import UserRole

from .context import audit_context_var
from .models import AuditLog

SENSITIVE_FIELDS = {
    'password',
    'password_hash',
    'token',
    'secret',
    'national_id',
    'identification_number',
    'phone',
    'phone_number',
    'mobile',
    'alternate_phone',
    'document_number',
    'passport_number',
    'email',
}


def _safe_values(values):
    if values is None:
        return None
    return {
        key: '[REDACTED]' if key.lower() in SENSITIVE_FIELDS else value
        for key, value in values.items()
    }


def log_action(
    action,
    entity,
    entity_id='',
    old_values=None,
    new_values=None,
    remarks='',
    branch_id=None,
):
    context = audit_context_var.get() or {}
    user = context.get('user')
    role_name = ''
    if user and user.is_authenticated:
        try:
            role_name = UserRole.objects.select_related('role').get(user=user).role.name
        except UserRole.DoesNotExist:
            role_name = ''
    return AuditLog.objects.create(
        user=user,
        user_name=user.get_username() if user else '',
        role_name=role_name,
        branch_id=branch_id if branch_id is not None else context.get('branch_id'),
        action=action,
        entity_name=entity,
        entity_id=str(entity_id),
        old_values=_safe_values(old_values),
        new_values=_safe_values(new_values),
        ip_address=context.get('ip_address'),
        user_agent=context.get('user_agent', ''),
        correlation_id=context.get('correlation_id', ''),
        remarks=remarks[:500],
    )
