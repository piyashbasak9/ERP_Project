from datetime import datetime, time, timedelta

from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.http import Http404, HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from core.branch.models import Branch

from .models import AuditLog


def _scoped_logs(request):
    queryset = AuditLog.objects.select_related("user", "branch")
    if not request.user.is_superuser:
        queryset = queryset.filter(
            branch_id__in=request.user.accessible_branch_ids(request.active_branch_id)
        )
    return queryset


def _parse_day(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("Dates must use YYYY-MM-DD format.") from None


def _apply_filters(request, queryset):
    action = request.GET.get("action", "").strip()[:40]
    entity = request.GET.get("entity", "").strip()[:100]
    username = request.GET.get("user", "").strip()[:150]
    ip_address = request.GET.get("ip", "").strip()[:45]
    start_date = _parse_day(request.GET.get("start_date", "").strip())
    end_date = _parse_day(request.GET.get("end_date", "").strip())
    branch_id = request.GET.get("branch", "").strip()
    if start_date:
        queryset = queryset.filter(
            timestamp_utc__gte=timezone.make_aware(datetime.combine(start_date, time.min))
        )
    if end_date:
        queryset = queryset.filter(
            timestamp_utc__lt=timezone.make_aware(
                datetime.combine(end_date + timedelta(days=1), time.min)
            )
        )
    if start_date and end_date and start_date > end_date:
        raise ValueError("The start date must be on or before the end date.")
    if action:
        queryset = queryset.filter(action__icontains=action)
    if entity:
        queryset = queryset.filter(entity_name__icontains=entity)
    if username:
        queryset = queryset.filter(user_name__icontains=username)
    if ip_address:
        queryset = queryset.filter(ip_address__icontains=ip_address)
    if branch_id:
        try:
            branch_id = int(branch_id)
        except ValueError:
            raise ValueError("Branch must be an integer.") from None
        allowed = request.user.accessible_branch_ids(request.active_branch_id)
        if not request.user.is_superuser and branch_id not in allowed:
            raise PermissionError("You cannot access that branch.")
        queryset = queryset.filter(branch_id=branch_id)
    return queryset, {
        "action": action,
        "entity": entity,
        "user": username,
        "ip": ip_address,
        "start_date": request.GET.get("start_date", ""),
        "end_date": request.GET.get("end_date", ""),
        "branch": branch_id if branch_id else "",
    }


@require_GET
def logs(request):
    try:
        queryset, filters = _apply_filters(request, _scoped_logs(request))
    except ValueError as error:
        return HttpResponseBadRequest(str(error))
    except PermissionError as error:
        return HttpResponseForbidden(str(error))
    page_size = getattr(request, "user_preference", None)
    page_size = page_size.default_page_size if page_size else 50
    paginator = Paginator(queryset.order_by("-timestamp_utc", "-pk"), page_size)
    page_obj = paginator.get_page(request.GET.get('page', 1))
    accessible = request.user.accessible_branch_ids(request.active_branch_id)
    return render(
        request,
        "audit/logs.html",
        {
            "page_obj": page_obj,
            "filters": filters,
            "branches": Branch.unscoped.filter(pk__in=accessible).order_by("name"),
        },
    )


@require_GET
def trail(request, entity, entity_id):
    logs = _scoped_logs(request).filter(
        entity_name=entity[:100], entity_id=entity_id[:100]
    )
    if not logs.exists():
        raise Http404("No audit history was found for this record.")
    entries = []
    for log in logs.order_by("-timestamp_utc", "-pk"):
        old_values = log.old_values or {}
        new_values = log.new_values or {}
        fields = sorted(set(old_values) | set(new_values))
        entries.append(
            {
                "log": log,
                "changes": [
                    {
                        "field": field,
                        "old": old_values.get(field, "—"),
                        "new": new_values.get(field, "—"),
                    }
                    for field in fields
                ],
            }
        )
    return render(
        request,
        "audit/trail.html",
        {
            "entity": entity,
            "entity_id": entity_id,
            "entries": entries,
        },
    )


@require_GET
def events(request):
    queryset = _scoped_logs(request).filter(
        action="SystemEvent", entity_name="SystemEvent"
    )
    try:
        queryset, filters = _apply_filters(request, queryset)
    except ValueError as error:
        return HttpResponseBadRequest(str(error))
    except PermissionError as error:
        return HttpResponseForbidden(str(error))
    page_obj = Paginator(queryset.order_by("-timestamp_utc", "-pk"), 50).get_page(
        request.GET.get("page", 1)
    )
    return render(
        request,
        "audit/events.html",
        {"page_obj": page_obj, "filters": filters},
    )


@require_GET
def dashboard(request):
    queryset = _scoped_logs(request)
    today = queryset.filter(timestamp_utc__date=timezone.localdate())
    logins_per_day = (
        queryset.filter(action="Login")
        .annotate(day=TruncDate("timestamp_utc"))
        .values("day")
        .annotate(count=Count("pk"))
        .order_by("-day")[:30]
    )
    return render(
        request,
        "audit/dashboard.html",
        {
            "logins_per_day": logins_per_day,
            "failed_logins_today": today.filter(
                action__in=["LoginFailed", "Lockout"]
            ).count(),
            "top_actions": queryset.values("action")
            .annotate(count=Count("pk"))
            .order_by("-count", "action")[:10],
            "most_active_users": queryset.exclude(user__isnull=True)
            .values("user_name")
            .annotate(count=Count("pk"))
            .order_by("-count", "user_name")[:10],
            "sensitive_actions": queryset.filter(
                Q(action__in=["Download", "Export", "ViewSensitiveData"])
                | Q(entity_name__icontains="kyc")
            ).order_by("-timestamp_utc", "-pk")[:20],
        },
    )
