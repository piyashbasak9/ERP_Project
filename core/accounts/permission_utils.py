import re
from django.urls import get_resolver, URLPattern, URLResolver
from ERP.db import SessionLocal
from .models_sa import Permission

PREFIX_WHITELIST = ('Module', 'API')


def get_all_urls():
    url_list = []
    resolver = get_resolver()

    def rec_search(pattern, prefix=''):
        if hasattr(pattern, 'url_patterns'):
            for sub_pattern in pattern.url_patterns:
                if isinstance(sub_pattern, URLPattern):
                    route_name = sub_pattern.name
                    if route_name and route_name.startswith(PREFIX_WHITELIST):
                        full_url = prefix + str(sub_pattern.pattern)
                        url_list.append({
                            'url': full_url,
                            'route_name': route_name,
                        })
                elif isinstance(sub_pattern, URLResolver):
                    rec_search(sub_pattern, prefix + str(sub_pattern.pattern))

    rec_search(resolver)
    return url_list


def sync_permission_route_names():
    all_routes = get_all_urls()
    if not all_routes:
        return 0

    url_to_name = {item['url']: item['route_name'] for item in all_routes}
    name_to_url = {item['route_name']: item['url'] for item in all_routes}

    session = SessionLocal()
    updated = 0
    try:
        permissions = session.query(Permission).filter(Permission.route_name == None).all()
        for perm in permissions:
            if perm.url_pattern in url_to_name:
                perm.route_name = url_to_name[perm.url_pattern]
                updated += 1
            elif perm.url_pattern in name_to_url:
                perm.route_name = perm.url_pattern
                updated += 1
            else:
                # fallback: exact match on route pattern if stored path uses Django parameter syntax
                for url, route_name in url_to_name.items():
                    if perm.url_pattern == url:
                        perm.route_name = route_name
                        updated += 1
                        break
        if updated:
            session.commit()
        return updated
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
