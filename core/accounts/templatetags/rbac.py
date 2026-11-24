from django import template

from core.accounts.permission_utils import user_has_route_permission
from core.common.ui_registry import VIEW_UI_TYPES

register = template.Library()


@register.simple_tag(takes_context=True)
def can(context, route_name):
    request = context.get('request')
    if request is None:
        return False
    return user_has_route_permission(request.user, route_name)


@register.simple_tag(takes_context=True)
def ui_page_type(context):
    request = context.get('request')
    if request is None or request.resolver_match is None:
        return 'unclassified'
    callback = request.resolver_match.func
    view = getattr(callback, 'view_class', None) or callback
    view_key = f'{view.__module__}.{view.__name__}'
    return VIEW_UI_TYPES.get(view_key, 'unclassified')
