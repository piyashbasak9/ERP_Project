from django.db import transaction
from django.urls import URLPattern, URLResolver, get_resolver

from .middleware import AUTHENTICATED_ONLY_ROUTE_NAMES, PUBLIC_ROUTE_NAMES
from .models import Permission


def get_all_urls():
    url_list = []
    resolver = get_resolver()

    def rec_search(pattern, prefix=''):
        for sub_pattern in getattr(pattern, 'url_patterns', []):
            if isinstance(sub_pattern, URLPattern):
                route_name = sub_pattern.name
                if (
                    route_name
                    and route_name.startswith(('Module', 'API'))
                    and route_name not in PUBLIC_ROUTE_NAMES
                    and route_name not in AUTHENTICATED_ONLY_ROUTE_NAMES
                ):
                    route = prefix + str(sub_pattern.pattern)
                    route_parts = route_name.removeprefix('Module_').split('_')
                    module = route_parts[0] if route_parts else ''
                    action = route_parts[-1] if route_parts else ''
                    url_list.append({
                        'url': route,
                        'route_name': route_name,
                        'module': module,
                        'action': action,
                        'description': f'{module} {action}'.strip(),
                    })
            elif isinstance(sub_pattern, URLResolver):
                rec_search(sub_pattern, prefix + str(sub_pattern.pattern))

    rec_search(resolver)
    return url_list


@transaction.atomic
def sync_permissions():
    routes = get_all_urls()
    route_names = [route['route_name'] for route in routes]

    for route in routes:
        permission = Permission.objects.filter(route_name=route['route_name']).first()
        if permission is None:
            permission = Permission.objects.filter(url_pattern=route['url']).first()
        if permission is None:
            Permission.objects.create(
                route_name=route['route_name'],
                url_pattern=route['url'],
                is_active=True,
                module=route['module'],
                action=route['action'],
                description=route['description'],
            )
        else:
            permission.route_name = route['route_name']
            permission.url_pattern = route['url']
            permission.is_active = True
            permission.module = route['module']
            permission.action = route['action']
            permission.description = route['description']
            permission.save()

    Permission.objects.exclude(route_name__in=route_names).update(is_active=False)
    return len(routes)


def sync_permission_route_names():
    return sync_permissions()
