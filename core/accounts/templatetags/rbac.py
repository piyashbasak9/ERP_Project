from django import template

from core.accounts.permission_utils import user_has_route_permission

register = template.Library()


@register.simple_tag(takes_context=True)
def can(context, route_name):
    request = context.get('request')
    if request is None:
        return False
    return user_has_route_permission(request.user, route_name)
