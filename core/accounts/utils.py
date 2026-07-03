from django.urls import get_resolver, URLPattern, URLResolver

def get_all_urls():
    url_list = []
    resolver = get_resolver()

    def rec_search(pattern, prefix=''):
        if hasattr(pattern, 'url_patterns'):
            for sub_pattern in pattern.url_patterns:
                if isinstance(sub_pattern, URLPattern):
                    full_url = prefix + str(sub_pattern.pattern)
                    url_list.append({
                        'url': full_url,
                        'name': sub_pattern.name if sub_pattern.name else full_url
                    })
                elif isinstance(sub_pattern, URLResolver):
                    rec_search(sub_pattern, prefix + str(sub_pattern.pattern))

    rec_search(resolver)
    return url_list