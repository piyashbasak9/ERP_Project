from .models import Branch


def branch_context(request):
    user = request.user
    if not user.is_authenticated or not user.is_active:
        return {'accessible_branches': [], 'active_branch': None}

    branches = Branch.unscoped.filter(
        pk__in=user.accessible_branch_ids(),
        is_active=True,
    ).order_by('hierarchy_path', 'name')
    return {
        'accessible_branches': branches,
        'active_branch': branches.filter(pk=getattr(request, 'active_branch_id', None)).first(),
    }
