from datetime import timedelta
from decimal import Decimal

from django.db.models import DecimalField, ExpressionWrapper, F, Sum
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone

from core.accounts.models import Permission
from core.branch.models import Member


def _dashboard_permissions(user):
    if user.is_superuser:
        return None
    return set(
        Permission.objects.filter(
            role_permissions__role__user_roles__user=user,
            role_permissions__role__user_roles__user__is_active=True,
            is_allowed=True,
            is_active=True,
        ).values_list("route_name", flat=True)
    )


def _dashboard_cards(request):
    from core.accounting.models import JournalEntry
    from core.collections.models import CollectionSheet, CollectionSheetItem
    from core.loans.models import Loan, LoanApplication, LoanInstallment
    from core.savings.models import SavingsAccount, SavingsTransaction

    permissions = _dashboard_permissions(request.user)
    branch_ids = request.user.accessible_branch_ids(request.active_branch_id)
    today = timezone.localdate()
    cards = []

    def permitted(route_name):
        return permissions is None or route_name in permissions

    def add(key, title, value, route_name):
        if permitted(route_name):
            display = (
                f"{value:,.2f}" if isinstance(value, Decimal) else f"{value:,}"
            )
            cards.append({"key": key, "title": title, "value": display})

    if permitted("Module_Members_list"):
        add(
            "active_members",
            "Active members",
            Member.objects.filter(
                branch_id__in=branch_ids, status=Member.STATUS_ACTIVE
            ).count(),
            "Module_Members_list",
        )

    if permitted("Module_Savings_balance_report"):
        savings_balance = (
            SavingsAccount.unscoped.filter(
                branch_id__in=branch_ids,
                status__in=[SavingsAccount.STATUS_ACTIVE, SavingsAccount.STATUS_DORMANT],
            ).aggregate(total=Sum("balance"))["total"]
            or Decimal("0.00")
        )
        add("savings_balance", "Savings balance", savings_balance, "Module_Savings_balance_report")

    loan_permission = permitted("Module_Loans_portfolio")
    if loan_permission:
        active_loans = Loan.unscoped.filter(
            branch_id__in=branch_ids, status=Loan.STATUS_ACTIVE
        )
        loan_totals = active_loans.aggregate(
            outstanding=Sum("outstanding_principal"),
            principal=Sum("principal"),
        )
        outstanding = loan_totals["outstanding"] or Decimal("0.00")
        principal = loan_totals["principal"] or Decimal("0.00")
        add("loans_outstanding", "Loans outstanding", outstanding, "Module_Loans_portfolio")

        overdue_expression = ExpressionWrapper(
            F("principal_due") - F("principal_paid")
            + F("interest_due") - F("interest_paid") - F("interest_waived")
            + F("fee_due") - F("fee_paid"),
            output_field=DecimalField(max_digits=18, decimal_places=2),
        )
        overdue = (
            LoanInstallment.objects.filter(
                loan__branch_id__in=branch_ids,
                loan__status=Loan.STATUS_ACTIVE,
                schedule_version=F("loan__schedule_version"),
                due_date__lt=today,
            )
            .annotate(remaining=overdue_expression)
            .filter(remaining__gt=0)
            .aggregate(total=Sum("remaining"))["total"]
            or Decimal("0.00")
        )
        add("overdue_amount", "Overdue amount", overdue, "Module_Loans_portfolio")

        for days in (1, 30, 90):
            overdue_loan_ids = (
                LoanInstallment.objects.filter(
                    loan__branch_id__in=branch_ids,
                    loan__status=Loan.STATUS_ACTIVE,
                    schedule_version=F("loan__schedule_version"),
                    due_date__lt=today - timedelta(days=days),
                )
                .annotate(remaining=overdue_expression)
                .filter(remaining__gt=0)
                .values("loan_id")
                .distinct()
            )
            at_risk = (
                active_loans.filter(pk__in=overdue_loan_ids).aggregate(
                    total=Sum("outstanding_principal")
                )["total"]
                or Decimal("0.00")
            )
            ratio = at_risk / principal * Decimal(100) if principal else Decimal(0)
            add(f"par_{days}", f"PAR {days}", ratio, "Module_Loans_portfolio")

    if permitted("Module_Collections_report_daily"):
        collections_today = (
            CollectionSheetItem.objects.filter(
                branch_id__in=branch_ids,
                sheet__collection_date=today,
                sheet__status=CollectionSheet.STATUS_POSTED,
            ).aggregate(total=Sum("collected_amount") + Sum("savings_amount"))["total"]
            or Decimal("0.00")
        )
        add(
            "todays_collection",
            "Today's collection",
            collections_today,
            "Module_Collections_report_daily",
        )

    if any(
        permitted(route)
        for route in (
            "Module_Loans_applications",
            "Module_Accounting_approval_queue",
            "Module_Savings_approve_withdrawal",
        )
    ):
        pending = 0
        if permitted("Module_Loans_applications"):
            pending += LoanApplication.objects.filter(
                branch_id__in=branch_ids, status=LoanApplication.STATUS_SUBMITTED
            ).count()
        if permitted("Module_Accounting_approval_queue"):
            pending += JournalEntry.objects.filter(
                branch_id__in=branch_ids, status=JournalEntry.STATUS_PENDING
            ).count()
        if permitted("Module_Savings_approve_withdrawal"):
            pending += SavingsTransaction.objects.filter(
                branch_id__in=branch_ids,
                status=SavingsTransaction.STATUS_PENDING,
            ).count()
        if pending_route := next(
            (
                route
                for route in (
                    "Module_Loans_applications",
                    "Module_Accounting_approval_queue",
                    "Module_Savings_approve_withdrawal",
                )
                if permitted(route)
            ),
            None,
        ):
            cards.append(
                {
                    "key": "pending_approvals",
                    "title": "Pending approvals",
                    "value": f"{pending:,}",
                    "permission": pending_route,
                }
            )

    return cards


def home(request):
    return render(request, 'home.html', {"dashboard_cards": _dashboard_cards(request)})


def health(request):
    return JsonResponse({'status': 'ok'})
