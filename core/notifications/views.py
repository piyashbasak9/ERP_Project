from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.html import format_html
from django.views.decorators.http import require_GET, require_POST

from core.accounts.permission_utils import user_has_route_permission
from core.audit.services import log_action
from core.common.templatetags.user_formatting import user_date

from .forms import (
    NotificationConfigurationForm,
    NotificationPreferenceForm,
    NotificationTemplateForm,
)
from .models import (
    Notification,
    NotificationConfiguration,
    NotificationPreference,
    NotificationTemplate,
)
from .services import mark_notification_read


@require_GET
def notification_list(request):
    branch_ids = request.user.accessible_branch_ids(
        getattr(request, "active_branch_id", None)
    )
    notifications = Notification.objects.filter(
        recipient=request.user,
        branch_id__in=branch_ids,
        channel=Notification.CHANNEL_IN_APP,
    )
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    if query:
        notifications = notifications.filter(
            Q(subject__icontains=query) | Q(body__icontains=query)
        )
    if status == "read":
        notifications = notifications.filter(is_read=True)
    elif status == "unread":
        notifications = notifications.filter(is_read=False)
    sort_fields = {
        "subject": "subject",
        "created_at": "created_at",
        "status": "is_read",
    }
    sort_field = sort_fields.get(request.GET.get("sidx"), "created_at")
    if request.GET.get("sord", "desc") != "asc":
        sort_field = f"-{sort_field}"
    try:
        page_size = min(max(int(request.GET.get("rows", 20)), 1), 200)
    except (TypeError, ValueError):
        page_size = 20
    paginator = Paginator(notifications.order_by(sort_field, "-pk"), page_size)
    page_obj = paginator.get_page(request.GET.get("page", 1))
    if request.GET.get("ajax") == "1":
        can_mark_read = user_has_route_permission(
            request.user, "Module_Notifications_mark_read"
        )
        csrf_token = get_token(request)
        rows = []
        for notification in page_obj.object_list:
            action = (
                format_html(
                    '<form method="post" action="{}">'
                    '<input type="hidden" name="csrfmiddlewaretoken" value="{}">'
                    '<button class="btn btn-sm btn-outline-primary" type="submit">'
                    'Mark as read</button></form>',
                    reverse(
                        "notifications:Module_Notifications_mark_read",
                        args=[notification.pk],
                    ),
                    csrf_token,
                )
                if not notification.is_read and can_mark_read
                else ""
            )
            rows.append({
                "id": notification.pk,
                "subject": notification.subject,
                "body": notification.body,
                "created_at": user_date(
                    notification.created_at, request.user_preference
                ),
                "status": "Read" if notification.is_read else "Unread",
                "actions": action,
            })
        return JsonResponse({
            "rows": rows,
            "page": page_obj.number,
            "total": paginator.num_pages,
            "records": paginator.count,
        })

    return render(request, "notifications/list.html", {
        "list_title": "Notifications",
        "grid_url": request.path,
        "initial_page_text": f"Page {page_obj.number} of {paginator.num_pages}",
        "default_sort_name": "created_at",
        "default_sort_order": "desc",
        "list_columns": [
            {"name": "subject", "label": "Notification", "width": 220, "priority": 1},
            {"name": "status", "label": "Status", "width": 100, "priority": 2},
            {"name": "created_at", "label": "Received", "width": 170, "priority": 2},
            {"name": "body", "label": "Message", "width": 360, "priority": 3},
            {"name": "actions", "label": "Actions", "width": 130, "priority": 1, "sortable": False},
        ],
        "list_filters": [
            {
                "name": "q",
                "label": "Search",
                "value": query,
                "placeholder": "Subject or message",
            },
            {
                "name": "status",
                "label": "Status",
                "type": "select",
                "value": status,
                "options": [("unread", "Unread"), ("read", "Read")],
            },
        ],
    })


@require_POST
def mark_read(request, pk):
    branch_ids = request.user.accessible_branch_ids(
        getattr(request, "active_branch_id", None)
    )
    if not mark_notification_read(
        notification_id=pk,
        user=request.user,
        branch_ids=branch_ids,
    ):
        return JsonResponse(
            {"success": False, "message": "Notification not found."},
            status=404,
        )
    if request.headers.get("x-requested-with") != "XMLHttpRequest":
        return redirect("notifications:Module_Notifications_list")
    return JsonResponse({"success": True})


@require_GET
def preferences(request):
    preference = NotificationPreference.objects.filter(user=request.user).first()
    if preference is None:
        preference = NotificationPreference(user=request.user)
    return render(
        request,
        "notifications/preferences.html",
        {"form": NotificationPreferenceForm(instance=preference)},
    )


@require_POST
def save_preferences(request):
    preference, _ = NotificationPreference.objects.get_or_create(user=request.user)
    old_values = {
        "email_enabled": preference.email_enabled,
        "in_app_enabled": preference.in_app_enabled,
        "sms_enabled": preference.sms_enabled,
    }
    form = NotificationPreferenceForm(request.POST, instance=preference)
    if not form.is_valid():
        return render(
            request,
            "notifications/preferences.html",
            {"form": form},
            status=400,
        )
    preference = form.save()
    log_action(
        "Update",
        "NotificationPreference",
        preference.pk,
        old_values=old_values,
        new_values={
            "email_enabled": preference.email_enabled,
            "in_app_enabled": preference.in_app_enabled,
            "sms_enabled": preference.sms_enabled,
        },
    )
    messages.success(request, "Notification preferences saved.")
    return redirect("notifications:Module_Notifications_preferences")


@require_GET
def settings_templates(request):
    configuration = NotificationConfiguration.current()
    event_key = request.GET.get("event_key", "")
    instance = NotificationTemplate.objects.filter(event_key=event_key).first()
    return render(
        request,
        "notifications/settings_templates.html",
        {
            "templates": NotificationTemplate.objects.order_by("event_key"),
            "form": NotificationTemplateForm(instance=instance),
            "configuration_form": NotificationConfigurationForm(
                instance=configuration
            ),
        },
    )


@require_POST
def save_settings_template(request):
    instance = None
    event_key = request.POST.get("event_key", "")
    if event_key:
        instance = NotificationTemplate.objects.filter(event_key=event_key).first()
    form = NotificationTemplateForm(request.POST, instance=instance)
    if not form.is_valid():
        return render(
            request,
            "notifications/settings_templates.html",
            {
                "templates": NotificationTemplate.objects.order_by("event_key"),
                "form": form,
                "configuration_form": NotificationConfigurationForm(
                    instance=NotificationConfiguration.current()
                ),
            },
            status=400,
        )
    template = form.save()
    log_action(
        "Update" if instance else "Create",
        "NotificationTemplate",
        template.pk,
        old_values=(
            {"subject": instance.subject, "body": instance.body, "enabled": instance.enabled}
            if instance
            else None
        ),
        new_values={"event_key": template.event_key, "enabled": template.enabled},
    )
    messages.success(request, "Notification template saved.")
    return redirect("configuration:Module_Settings_notification_templates")


@require_POST
def save_settings_configuration(request):
    configuration = NotificationConfiguration.current()
    old_days_before = configuration.installment_days_before
    form = NotificationConfigurationForm(request.POST, instance=configuration)
    if not form.is_valid():
        return render(
            request,
            "notifications/settings_templates.html",
            {
                "templates": NotificationTemplate.objects.order_by("event_key"),
                "form": NotificationTemplateForm(),
                "configuration_form": form,
            },
            status=400,
        )
    configuration = form.save()
    log_action(
        "Update",
        "NotificationConfiguration",
        configuration.pk,
        old_values={"installment_days_before": old_days_before},
        new_values={
            "installment_days_before": configuration.installment_days_before
        },
    )
    messages.success(request, "Notification schedule saved.")
    return redirect("configuration:Module_Settings_notification_templates")
