from django import template

from core.accounts.models import UserRole

register = template.Library()


@register.simple_tag(takes_context=True)
def can(context, route_name):
    request = context.get('request')
    if request is None:
        return False
    user = request.user
    if not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser:
        return True
    return UserRole.objects.filter(
        user=user,
        role__permissions__route_name=route_name,
        role__permissions__is_allowed=True,
        role__permissions__is_active=True,
    ).exists()
