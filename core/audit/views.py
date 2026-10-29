from django.core.paginator import Paginator
from django.shortcuts import render
from django.views.decorators.http import require_GET

from .models import AuditLog


@require_GET
def logs(request):
    queryset = AuditLog.objects.select_related('user', 'branch')
    if not request.user.is_superuser:
        queryset = queryset.filter(
            branch_id__in=request.user.accessible_branch_ids(request.active_branch_id)
        )
    if action := request.GET.get('action', '').strip():
        queryset = queryset.filter(action__icontains=action[:40])
    if entity := request.GET.get('entity', '').strip():
        queryset = queryset.filter(entity_name__icontains=entity[:100])
    if username := request.GET.get('user', '').strip():
        queryset = queryset.filter(user_name__icontains=username[:150])

    paginator = Paginator(queryset, 50)
    page_obj = paginator.get_page(request.GET.get('page', 1))
    return render(request, 'audit/logs.html', {
        'page_obj': page_obj,
        'filters': {
            'action': action if 'action' in locals() else '',
            'entity': entity if 'entity' in locals() else '',
            'user': username if 'username' in locals() else '',
        },
    })
