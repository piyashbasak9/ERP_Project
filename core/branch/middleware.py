from core.common.context import current_branch_id_var, current_user_var


class BranchContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user_token = current_user_var.set(
            request.user if request.user.is_authenticated and request.user.is_active else None
        )
        active_branch_id = request.session.get('active_branch_id')
        if active_branch_id is not None and request.user.is_authenticated:
            try:
                active_branch_id = int(active_branch_id)
            except (TypeError, ValueError):
                active_branch_id = None

            if active_branch_id not in request.user.accessible_branch_ids():
                request.session.pop('active_branch_id', None)
                active_branch_id = None

        branch_token = current_branch_id_var.set(active_branch_id)
        request.active_branch_id = active_branch_id
        try:
            return self.get_response(request)
        finally:
            current_branch_id_var.reset(branch_token)
            current_user_var.reset(user_token)
