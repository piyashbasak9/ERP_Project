from django.conf import settings
from django.db.models import Q
from django_otp.plugins.otp_totp.models import TOTPDevice

from .models import Permission

PRIVILEGED_PERMISSION_FRAGMENTS = (
    'role',
    'user',
    'setting',
    'configuration',
    'reopen',
    'reverse',
    'reversal',
)

SENSITIVE_ROUTE_FRAGMENTS = (
    'reopen',
    'reverse',
    'reversal',
    'edit_role',
    'edit_user',
    'mfa_reset',
    'create_role',
    'create_user',
    'delete_role',
    'delete_user',
    'permission',
)


def user_requires_mfa(user):
    if not getattr(user, 'is_authenticated', False) or not getattr(user, 'is_active', False):
        return False
    if not getattr(settings, 'MFA_REQUIRED', True):
        return False
    if user.is_superuser:
        return True
    privileged_permissions = Q()
    for fragment in PRIVILEGED_PERMISSION_FRAGMENTS:
        privileged_permissions |= Q(
            route_name__icontains=fragment,
        ) | Q(url_pattern__icontains=fragment)
    return Permission.objects.filter(
        role_permissions__role__user_roles__user=user,
        is_active=True,
        is_allowed=True,
    ).filter(privileged_permissions).exists()


def confirmed_totp_device(user):
    return TOTPDevice.objects.filter(user=user, confirmed=True).order_by('pk').first()


def is_sensitive_route(route_name):
    route_name = (route_name or '').lower()
    return any(fragment in route_name for fragment in SENSITIVE_ROUTE_FRAGMENTS)
