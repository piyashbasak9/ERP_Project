from django.contrib import messages
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from core.audit.services import log_action

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
    page_obj = Paginator(
        Notification.objects.filter(
            recipient=request.user,
            branch_id__in=branch_ids,
            channel=Notification.CHANNEL_IN_APP,
        ).order_by("-created_at", "-pk"),
        25,
    ).get_page(request.GET.get("page", 1))
    return render(request, "notifications/list.html", {"page_obj": page_obj})


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
