from datetime import datetime, time, timedelta

from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.http import (
    Http404,
    HttpResponseBadRequest,
    HttpResponseForbidden,
    JsonResponse,
)
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from django.views.decorators.http import require_GET

from core.accounts.permission_utils import user_has_route_permission
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


def _apply_filters(request, queryset, *, filter_action=True):
    action = request.GET.get("action", "").strip()[:40] if filter_action else ""
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
    order_fields = {
        "timestamp": "timestamp_utc",
        "user": "user_name",
        "branch": "branch__code",
        "action": "action",
        "entity": "entity_name",
        "record": "entity_id",
        "ip": "ip_address",
        "remarks": "remarks",
    }
    order = order_fields.get(request.GET.get("sidx", "timestamp"), "timestamp_utc")
    if request.GET.get("sord", "desc").lower() == "desc":
        order = f"-{order}"
    try:
        page_size = min(max(int(request.GET.get("rows", 20)), 1), 200)
    except (TypeError, ValueError):
        page_size = 20
    paginator = Paginator(queryset.order_by(order, "-pk"), page_size)
    page_obj = paginator.get_page(request.GET.get('page', 1))
    accessible = request.user.accessible_branch_ids(request.active_branch_id)
    branches = Branch.unscoped.filter(pk__in=accessible).order_by("name")
    if request.GET.get("ajax") == "1":
        can_view_trail = user_has_route_permission(
            request.user, "Module_Audit_trail"
        )
        rows = []
        for entry in page_obj.object_list:
            actions = []
            if (
                can_view_trail
                and entry.entity_id
                and "/" not in entry.entity_name
                and "/" not in entry.entity_id
            ):
                actions.append(format_html(
                    '<a href="{}">View</a>',
                    reverse(
                        "audit:Module_Audit_trail",
                        args=[entry.entity_name, entry.entity_id],
                    ),
                ))
            rows.append({
                "id": entry.pk,
                "timestamp": timezone.localtime(entry.timestamp_utc).strftime(
                    "%d-%b-%Y %H:%M:%S"
                ),
                "user": entry.user_name or "System",
                "branch": entry.branch.code if entry.branch_id else "—",
                "action": entry.action,
                "entity": entry.entity_name,
                "record": entry.entity_id or "—",
                "ip": entry.ip_address or "—",
                "remarks": entry.remarks or "—",
                "actions": format_html_join(
                    " | ", "{}", ((action,) for action in actions)
                ),
            })
        return JsonResponse({
            "rows": rows,
            "page": page_obj.number,
            "total": paginator.num_pages,
            "records": paginator.count,
        })

    return render(
        request,
        "audit/logs.html",
        {
            "page_obj": page_obj,
            "filters": filters,
            "list_title": "Audit log",
            "grid_url": request.path,
            "filter_layout": "members",
            "default_sort_name": "timestamp",
            "default_sort_order": "desc",
            "initial_page_text": f"Page {page_obj.number} of {paginator.num_pages}",
            "list_actions": [],
            "add_url": "",
            "add_title": "",
            "branches": branches,
            "list_filters": [
                {
                    "name": "action", "label": "Action",
                    "value": filters["action"], "placeholder": "Action",
                },
                {
                    "name": "entity", "label": "Entity",
                    "value": filters["entity"], "placeholder": "Entity",
                },
                {
                    "name": "user", "label": "User",
                    "value": filters["user"], "placeholder": "Username",
                },
                {
                    "name": "ip", "label": "IP address",
                    "value": filters["ip"], "placeholder": "IP address",
                },
                {
                    "name": "date", "label": "Date",
                    "type": "date-range",
                    "from_name": "start_date",
                    "from_value": filters["start_date"],
                    "to_name": "end_date",
                    "to_value": filters["end_date"],
                },
                {
                    "name": "branch", "label": "Branch",
                    "type": "select", "value": str(filters["branch"]),
                    "options": [
                        (str(branch.pk), branch.name) for branch in branches
                    ],
                },
            ],
            "list_columns": [
                {"name": "timestamp", "label": "Time", "width": 170},
                {"name": "user", "label": "User", "width": 140},
                {"name": "branch", "label": "Branch", "width": 100},
                {"name": "action", "label": "Action", "width": 130},
                {"name": "entity", "label": "Entity", "width": 140},
                {"name": "record", "label": "Record", "width": 100},
                {"name": "ip", "label": "IP address", "width": 140},
                {"name": "remarks", "label": "Remarks", "width": 220},
                {"name": "actions", "label": "Actions", "width": 90},
            ],
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
    category = request.GET.get(
        "category", request.GET.get("action", "")
    ).strip()[:40]
    severity = request.GET.get("severity", "").strip().lower()
    if severity not in {"info", "warning", "error", "critical"}:
        severity = ""
    event_status = request.GET.get("status", "").strip()[:32]
    message = request.GET.get("message", "").strip()[:500]
    if category:
        queryset = queryset.filter(new_values__category__icontains=category)
    if severity:
        queryset = queryset.filter(new_values__severity=severity)
    if event_status:
        queryset = queryset.filter(new_values__status__icontains=event_status)
    if message:
        queryset = queryset.filter(new_values__message__icontains=message)
    try:
        queryset, filters = _apply_filters(
            request, queryset, filter_action=False
        )
    except ValueError as error:
        return HttpResponseBadRequest(str(error))
    except PermissionError as error:
        return HttpResponseForbidden(str(error))
    order_fields = {
        "timestamp": "timestamp_utc",
        "category": "new_values__category",
        "severity": "new_values__severity",
        "status": "new_values__status",
        "message": "new_values__message",
        "branch": "branch__name",
    }
    order = order_fields.get(request.GET.get("sidx", "timestamp"), "timestamp_utc")
    if request.GET.get("sord", "desc").lower() == "desc":
        order = f"-{order}"
    try:
        page_size = min(max(int(request.GET.get("rows", 20)), 1), 200)
    except (TypeError, ValueError):
        page_size = 20
    paginator = Paginator(queryset.order_by(order, "-pk"), page_size)
    page_obj = paginator.get_page(request.GET.get("page", 1))
    accessible = request.user.accessible_branch_ids(request.active_branch_id)
    branches = Branch.unscoped.filter(pk__in=accessible).order_by("name")
    if request.GET.get("ajax") == "1":
        rows = []
        for event in page_obj.object_list:
            values = event.new_values or {}
            rows.append({
                "id": event.pk,
                "timestamp": timezone.localtime(event.timestamp_utc).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "category": values.get("category", ""),
                "severity": values.get("severity", ""),
                "status": values.get("status", ""),
                "message": values.get("message", ""),
                "branch": event.branch.name if event.branch_id else "—",
            })
        return JsonResponse({
            "rows": rows,
            "page": page_obj.number,
            "total": paginator.num_pages,
            "records": paginator.count,
        })

    return render(
        request,
        "audit/events.html",
        {
            "list_title": "System events",
            "grid_url": request.path,
            "filter_layout": "members",
            "default_sort_name": "timestamp",
            "default_sort_order": "desc",
            "initial_page_text": f"Page {page_obj.number} of {paginator.num_pages}",
            "list_actions": [],
            "add_url": "",
            "add_title": "",
            "list_filters": [
                {
                    "name": "category", "label": "Category",
                    "value": category, "placeholder": "Category",
                },
                {
                    "name": "severity", "label": "Severity",
                    "type": "select", "value": severity,
                    "options": (
                        ("info", "Info"),
                        ("warning", "Warning"),
                        ("error", "Error"),
                        ("critical", "Critical"),
                    ),
                },
                {
                    "name": "status", "label": "Status",
                    "value": event_status, "placeholder": "Status",
                },
                {
                    "name": "message", "label": "Message",
                    "value": message, "placeholder": "Message",
                },
                {
                    "name": "date", "label": "Date",
                    "type": "date-range",
                    "from_name": "start_date",
                    "from_value": filters["start_date"],
                    "to_name": "end_date",
                    "to_value": filters["end_date"],
                },
                {
                    "name": "branch", "label": "Branch",
                    "type": "select", "value": str(filters["branch"]),
                    "options": [
                        (str(branch.pk), branch.name) for branch in branches
                    ],
                },
            ],
            "list_columns": [
                {"name": "timestamp", "label": "Time", "width": 175},
                {"name": "category", "label": "Category", "width": 130},
                {"name": "severity", "label": "Severity", "width": 100},
                {"name": "status", "label": "Status", "width": 120},
                {"name": "message", "label": "Message", "width": 360},
                {"name": "branch", "label": "Branch", "width": 160},
            ],
            "page_obj": page_obj,
            "filters": filters,
        },
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
