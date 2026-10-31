from .models import Notification


def notification_context(request):
    if not request.user.is_authenticated:
        return {"unread_notification_count": 0}
    branch_ids = request.user.accessible_branch_ids(
        getattr(request, "active_branch_id", None)
    )
    count = Notification.objects.filter(
        recipient=request.user,
        branch_id__in=branch_ids,
        channel=Notification.CHANNEL_IN_APP,
        is_read=False,
    ).count()
    return {"unread_notification_count": count}
