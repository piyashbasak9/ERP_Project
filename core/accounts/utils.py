from django.urls import get_resolver, URLPattern, URLResolver

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