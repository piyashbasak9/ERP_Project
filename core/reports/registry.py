from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db.models import (
    Case,
    Count,
    DecimalField,
    ExpressionWrapper,
    F,
    Q,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce
from django.utils import timezone

ZERO = Decimal("0.00")
MONEY = DecimalField(max_digits=18, decimal_places=2)


@dataclass(frozen=True)
class ReportColumn:
    key: str
    label: str
    accessor: str | None = None


@dataclass(frozen=True)
class ReportDefinition:
    slug: str
    title: str
    group: str
    route_name: str
    columns: tuple[ReportColumn, ...]
    queryset: Callable[..., object]
    total_keys: tuple[str, ...] = ()
    center_field: str | None = None
    officer_field: str | None = None
    date_field: str | None = None
    status_field: str | None = None

    @property
    def grid_route_name(self):
        return f"Module_Reports_{self.slug.replace('-', '_')}_grid"

    @property
    def excel_route_name(self):
        return f"Module_Reports_{self.slug.replace('-', '_')}_excel"

    @property
    def pdf_route_name(self):
        return f"Module_Reports_{self.slug.replace('-', '_')}_pdf"


def _date_status_filters(queryset, report, filters):
    if report.date_field:
        if report.date_field == "timestamp_utc":
            if filters.start_date:
                start = timezone.make_aware(
                    datetime.combine(filters.start_date, time.min)
                )
                queryset = queryset.filter(
                    **{f"{report.date_field}__gte": start}
                )
            if filters.end_date:
                end = timezone.make_aware(
                    datetime.combine(filters.end_date + timedelta(days=1), time.min)
                )
                queryset = queryset.filter(
                    **{f"{report.date_field}__lt": end}
                )
        else:
            if filters.start_date:
                queryset = queryset.filter(
                    **{f"{report.date_field}__gte": filters.start_date}
                )
            if filters.end_date:
                queryset = queryset.filter(
                    **{f"{report.date_field}__lte": filters.end_date}
                )
    if report.status_field and filters.status:
        queryset = queryset.filter(**{report.status_field: filters.status})
    if report.center_field and filters.center_id:
        queryset = queryset.filter(**{report.center_field: filters.center_id})
    if report.officer_field and filters.officer_id:
        queryset = queryset.filter(**{report.officer_field: filters.officer_id})
    return queryset


def _financial_lines(filters):
    from core.accounting.models import JournalEntry, JournalLine

    return JournalLine.objects.filter(
        entry__branch_id__in=filters.branch_ids,
        entry__status=JournalEntry.STATUS_POSTED,
    ).select_related("entry__branch", "account")


def _general_ledger(request, filters):
    report = REPORTS_BY_SLUG["general-ledger"]
    return _date_status_filters(_financial_lines(filters), report, filters)


def _cash_book(request, filters):
    from core.accounting.models import SystemAccountMapping

    account_ids = SystemAccountMapping.objects.filter(
        key__in=("cash_in_hand", "bank_accounts"),
        account__is_active=True,
    ).values_list("account_id", flat=True)
    queryset = _financial_lines(filters).filter(account_id__in=account_ids)
    return _date_status_filters(
        queryset, REPORTS_BY_SLUG["cash-book"], filters
    )


def _trial_balance(request, filters):
    from datetime import date

    from core.accounting.services import build_trial_balance

    result = build_trial_balance(
        start_date=filters.start_date or date.min,
        end_date=filters.end_date,
        branch_ids=filters.branch_ids,
    )
    return [
        {
            "account": row["account"],
            "opening_debit": row["opening_debit"],
            "opening_credit": row["opening_credit"],
            "debit": row["debit"],
            "credit": row["credit"],
            "closing_debit": row["closing_debit"],
            "closing_credit": row["closing_credit"],
        }
        for row in result["accounts"]
    ]


def _income_statement(request, filters):
    from core.accounting.models import Account

    report = REPORTS_BY_SLUG["income-statement"]
    queryset = _date_status_filters(
        _financial_lines(filters).filter(
            account__account_type__in=(Account.INCOME, Account.EXPENSE)
        ),
        report,
        filters,
    )
    grouped = queryset.values(
        "account__code", "account__name", "account__account_type"
    ).annotate(
        debit=Coalesce(Sum("debit"), Value(ZERO), output_field=MONEY),
        credit=Coalesce(Sum("credit"), Value(ZERO), output_field=MONEY),
    )
    return grouped.annotate(
        amount=ExpressionWrapper(
            F("credit") - F("debit"),
            output_field=MONEY,
        )
    ).order_by("account__code")


def _balance_sheet(request, filters):
    from core.accounting.models import Account, FiscalYear

    lines = _financial_lines(filters).filter(entry__journal_date__lte=filters.end_date)
    grouped = lines.values(
        "account_id",
        "account__code",
        "account__name",
        "account__account_type",
        "account__normal_balance",
    ).annotate(
        debit=Coalesce(Sum("debit"), Value(ZERO), output_field=MONEY),
        credit=Coalesce(Sum("credit"), Value(ZERO), output_field=MONEY),
    ).order_by("account__code")
    rows = []
    for row in grouped:
        account_type = row["account__account_type"]
        if account_type not in (Account.ASSET, Account.LIABILITY, Account.EQUITY):
            continue
        net = row["debit"] - row["credit"]
        amount = net if row["account__normal_balance"] == Account.DEBIT else -net
        rows.append(
            {
                "code": row["account__code"],
                "account": row["account__name"],
                "account_type": account_type,
                "amount": amount,
            }
        )

    fiscal_year = FiscalYear.objects.filter(
        start_date__lte=filters.end_date,
        end_date__gte=filters.end_date,
    ).first()
    year_start = fiscal_year.start_date if fiscal_year else filters.end_date.replace(month=1, day=1)
    current_result = _financial_lines(filters).filter(
        entry__journal_date__range=(year_start, filters.end_date),
        account__account_type__in=(Account.INCOME, Account.EXPENSE),
    ).aggregate(
        income=Sum(
            Case(
                When(
                    account__account_type=Account.INCOME,
                    then=F("credit") - F("debit"),
                ),
                default=Value(ZERO),
                output_field=MONEY,
            )
        ),
        expense=Sum(
            Case(
                When(
                    account__account_type=Account.EXPENSE,
                    then=F("debit") - F("credit"),
                ),
                default=Value(ZERO),
                output_field=MONEY,
            )
        ),
    )
    rows.append(
        {
            "code": "",
            "account": "Current-year result",
            "account_type": Account.EQUITY,
            "amount": (current_result["income"] or ZERO)
            - (current_result["expense"] or ZERO),
        }
    )
    return rows


def _receipts_payments(request, filters):
    from core.accounting.models import SystemAccountMapping

    account_ids = SystemAccountMapping.objects.filter(
        key__in=("cash_in_hand", "bank_accounts"),
        account__is_active=True,
    ).values_list("account_id", flat=True)
    return _date_status_filters(
        _financial_lines(filters).filter(account_id__in=account_ids),
        REPORTS_BY_SLUG["receipts-payments"],
        filters,
    )


def _loan_queryset(filters):
    from core.loans.models import Loan

    queryset = Loan.objects.filter(branch_id__in=filters.branch_ids).select_related(
        "branch", "member", "member__center", "product"
    )
    return queryset


def _disbursement_register(request, filters):
    return _date_status_filters(
        _loan_queryset(filters),
        REPORTS_BY_SLUG["disbursement-register"],
        filters,
    )


def _outstanding_loans(request, filters):
    from core.loans.models import Loan

    return _date_status_filters(
        _loan_queryset(filters).filter(status=Loan.STATUS_ACTIVE),
        REPORTS_BY_SLUG["outstanding-loans"],
        filters,
    )


def _overdue_installments(request, filters):
    from core.loans.models import Loan, LoanInstallment

    remaining = ExpressionWrapper(
        F("principal_due")
        - F("principal_paid")
        + F("interest_due")
        - F("interest_paid")
        - F("interest_waived")
        + F("fee_due")
        - F("fee_paid"),
        output_field=MONEY,
    )
    queryset = LoanInstallment.objects.filter(
        loan__branch_id__in=filters.branch_ids,
        loan__status=Loan.STATUS_ACTIVE,
        schedule_version=F("loan__schedule_version"),
        due_date__lt=filters.end_date,
    ).annotate(remaining=remaining).filter(remaining__gt=ZERO).select_related(
        "loan__branch", "loan__member", "loan__member__center", "loan"
    )
    report = REPORTS_BY_SLUG["overdue-loans"]
    queryset = _date_status_filters(queryset, report, filters)
    if filters.center_id:
        queryset = queryset.filter(loan__member__center_id=filters.center_id)
    if filters.officer_id:
        queryset = queryset.filter(
            loan__member__center__field_officer_id=filters.officer_id
        )
    return queryset


def _loan_aging(request, filters):
    rows = _overdue_installments(request, filters).order_by("due_date", "loan_id")
    for row in rows:
        row.days_past_due = (filters.end_date - row.due_date).days
        row.aging_bucket = (
            "1-30"
            if row.days_past_due <= 30
            else "31-60"
            if row.days_past_due <= 60
            else "61-90"
            if row.days_past_due <= 90
            else "90+"
        )
    return rows


def _writeoffs(request, filters):
    from core.loans.models import Loan

    return _date_status_filters(
        _loan_queryset(filters).filter(status=Loan.STATUS_WRITTEN_OFF),
        REPORTS_BY_SLUG["write-offs"],
        filters,
    )


def _repayment_schedule(request, filters):
    from core.loans.models import LoanInstallment

    queryset = LoanInstallment.objects.filter(
        loan__branch_id__in=filters.branch_ids,
        schedule_version=F("loan__schedule_version"),
    ).select_related("loan__branch", "loan__member", "loan__member__center")
    report = REPORTS_BY_SLUG["repayment-schedule"]
    queryset = _date_status_filters(queryset, report, filters)
    if filters.center_id:
        queryset = queryset.filter(loan__member__center_id=filters.center_id)
    if filters.officer_id:
        queryset = queryset.filter(
            loan__member__center__field_officer_id=filters.officer_id
        )
    return queryset


def _portfolio_at_risk(request, filters):
    from core.loans.models import Loan, LoanInstallment

    loans = _loan_queryset(filters).filter(status=Loan.STATUS_ACTIVE)
    if filters.center_id:
        loans = loans.filter(member__center_id=filters.center_id)
    if filters.officer_id:
        loans = loans.filter(member__center__field_officer_id=filters.officer_id)
    loans = list(loans)
    principal = sum((loan.outstanding_principal for loan in loans), ZERO)
    rows = []
    for days in (1, 30, 90):
        threshold_date = filters.end_date - timedelta(days=days)
        at_risk = ZERO
        for loan in loans:
            overdue = LoanInstallment.objects.filter(
                loan=loan,
                schedule_version=loan.schedule_version,
                due_date__lt=threshold_date,
            ).filter(
                Q(principal_paid__lt=F("principal_due"))
                | Q(interest_paid__lt=F("interest_due") - F("interest_waived"))
            ).exists()
            if overdue:
                at_risk += loan.outstanding_principal
        rows.append(
            {
                "threshold": days,
                "amount": at_risk,
                "percentage": (
                    (at_risk / principal * 100).quantize(Decimal("0.01"))
                    if principal
                    else ZERO
                ),
                "portfolio": principal,
            }
        )
    return rows


def _loan_statement(request, filters):
    from core.loans.models import LoanPayment

    queryset = LoanPayment.objects.filter(
        branch_id__in=filters.branch_ids
    ).select_related(
        "branch",
        "loan",
        "loan__member",
        "loan__member__center",
    )
    report = REPORTS_BY_SLUG["loan-statement"]
    return _date_status_filters(queryset, report, filters)


def _classification(request, filters):
    from core.loans.services import LoanService

    result = LoanService(request).classification_report(
        as_of_date=filters.end_date,
        branch_ids=set(filters.branch_ids),
    )
    return [
        {
            "class": bucket["name"],
            "days": f'{bucket["minimum_days"]}-{bucket["maximum_days"] or "and above"}',
            "loan_count": bucket["loan_count"],
            "principal": bucket["principal"],
            "provision_rate": bucket["provision_rate"],
            "provision": bucket["provision"],
        }
        for bucket in result["buckets"]
    ]


def _savings_accounts(filters):
    from core.savings.models import SavingsAccount

    return SavingsAccount.objects.filter(branch_id__in=filters.branch_ids).select_related(
        "branch", "product", "member", "member__center", "group", "group__center"
    )


def _savings_account_list(request, filters):
    queryset = _date_status_filters(
        _savings_accounts(filters),
        REPORTS_BY_SLUG["account-list"],
        filters,
    )
    if filters.center_id:
        queryset = queryset.filter(
            Q(member__center_id=filters.center_id)
            | Q(group__center_id=filters.center_id)
        )
    if filters.officer_id:
        queryset = queryset.filter(
            Q(member__center__field_officer_id=filters.officer_id)
            | Q(group__center__field_officer_id=filters.officer_id)
        )
    return queryset


def _savings_transactions(request, filters):
    from core.savings.models import SavingsTransaction

    queryset = SavingsTransaction.objects.filter(
        branch_id__in=filters.branch_ids
    ).select_related(
        "branch", "account", "account__member", "account__member__center", "account__product"
    )
    report = REPORTS_BY_SLUG["transaction-register"]
    queryset = _date_status_filters(queryset, report, filters)
    if filters.center_id:
        queryset = queryset.filter(
            Q(account__member__center_id=filters.center_id)
            | Q(account__group__center_id=filters.center_id)
        )
    if filters.officer_id:
        queryset = queryset.filter(
            Q(account__member__center__field_officer_id=filters.officer_id)
            | Q(account__group__center__field_officer_id=filters.officer_id)
        )
    return queryset


def _savings_summary(request, filters):
    from core.savings.models import SavingsAccount

    queryset = _date_status_filters(
        _savings_accounts(filters).filter(
            status__in=(SavingsAccount.STATUS_ACTIVE, SavingsAccount.STATUS_DORMANT)
        ),
        REPORTS_BY_SLUG["balance-summary"],
        filters,
    )
    grouped = queryset.values(
        "branch__name", "product__code", "product__name", "status"
    ).annotate(
        account_count=Count("pk"),
        balance=Coalesce(Sum("balance"), Value(ZERO), output_field=MONEY),
        reserved=Coalesce(Sum("reserved_balance"), Value(ZERO), output_field=MONEY),
    )
    return grouped.annotate(
        available=ExpressionWrapper(
            F("balance") - F("reserved"),
            output_field=MONEY,
        )
    ).order_by("branch__name", "product__code", "status")


def _interest_posted(request, filters):
    from core.savings.models import SavingsTransaction

    return _savings_transactions(request, filters).filter(
        transaction_type=SavingsTransaction.TYPE_INTEREST,
        status=SavingsTransaction.STATUS_POSTED,
    )


def _dormant_accounts(request, filters):
    from core.savings.models import SavingsAccount

    queryset = _date_status_filters(
        _savings_accounts(filters).filter(status=SavingsAccount.STATUS_DORMANT),
        REPORTS_BY_SLUG["dormant-accounts"],
        filters,
    )
    if filters.center_id:
        queryset = queryset.filter(
            Q(member__center_id=filters.center_id)
            | Q(group__center_id=filters.center_id)
        )
    if filters.officer_id:
        queryset = queryset.filter(
            Q(member__center__field_officer_id=filters.officer_id)
            | Q(group__center__field_officer_id=filters.officer_id)
        )
    return queryset


def _member_queryset(filters):
    from core.branch.models import Member

    return Member.objects.filter(branch_id__in=filters.branch_ids).select_related(
        "branch", "center", "center__field_officer", "group"
    )


def _member_list(request, filters):
    return _date_status_filters(
        _member_queryset(filters),
        REPORTS_BY_SLUG["member-list"],
        filters,
    )


def _new_members(request, filters):
    return _date_status_filters(
        _member_queryset(filters),
        REPORTS_BY_SLUG["new-members"],
        filters,
    )


def _member_status_summary(request, filters):
    return _date_status_filters(
        _member_queryset(filters),
        REPORTS_BY_SLUG["status-summary"],
        filters,
    ).values("branch__name", "status").annotate(
        member_count=Count("pk")
    ).order_by("branch__name", "status")


def _kyc_report(request, filters):
    from core.branch.models import MemberKYC

    report = REPORTS_BY_SLUG["kyc-pending-expired"]
    queryset = MemberKYC.objects.filter(
        member__branch_id__in=filters.branch_ids
    ).select_related(
        "member__branch", "member__center", "member__center__field_officer"
    )
    queryset = _date_status_filters(queryset, report, filters)
    if not filters.status:
        queryset = queryset.filter(
            Q(status=MemberKYC.STATUS_PENDING)
            | Q(expiry_date__lt=filters.end_date)
        )
    if filters.center_id:
        queryset = queryset.filter(member__center_id=filters.center_id)
    if filters.officer_id:
        queryset = queryset.filter(
            member__center__field_officer_id=filters.officer_id
        )
    return queryset


def _member_statement(request, filters):
    from core.loans.models import LoanPayment
    from core.savings.models import SavingsTransaction

    rows = []
    savings = SavingsTransaction.objects.filter(
        branch_id__in=filters.branch_ids,
        account__member__isnull=False,
    ).select_related("account", "account__member")
    payments = LoanPayment.objects.filter(
        branch_id__in=filters.branch_ids
    ).select_related("loan", "loan__member")
    for entry_date, amount, description, member, kind in (
        (row.transaction_date, row.amount, row.get_transaction_type_display(), row.account.member, "savings")
        for row in savings
    ):
        if member is not None:
            rows.append(
                {
                    "date": entry_date,
                    "member": member.full_name,
                    "member_code": member.member_code,
                    "type": kind,
                    "description": description,
                    "debit": amount if description in ("Withdrawal", "Fee") else ZERO,
                    "credit": amount if description in ("Deposit", "Interest") else ZERO,
                }
            )
    for row in payments:
        rows.append(
            {
                "date": row.payment_date,
                "member": row.loan.member.full_name,
                "member_code": row.loan.member.member_code,
                "type": "loan",
                "description": "Loan repayment",
                "debit": row.amount,
                "credit": ZERO,
            }
        )
    if filters.start_date:
        rows = [row for row in rows if row["date"] >= filters.start_date]
    if filters.end_date:
        rows = [row for row in rows if row["date"] <= filters.end_date]
    if filters.center_id:
        members = _member_queryset(filters).filter(center_id=filters.center_id)
        codes = set(members.values_list("member_code", flat=True))
        rows = [row for row in rows if row["member_code"] in codes]
    if filters.officer_id:
        members = _member_queryset(filters).filter(
            center__field_officer_id=filters.officer_id
        )
        codes = set(members.values_list("member_code", flat=True))
        rows = [row for row in rows if row["member_code"] in codes]
    if filters.status:
        members = _member_queryset(filters).filter(status=filters.status)
        codes = set(members.values_list("member_code", flat=True))
        rows = [row for row in rows if row["member_code"] in codes]
    return sorted(rows, key=lambda row: (row["date"], row["member_code"]))


def _collection_sheets(filters):
    from core.collections.models import CollectionSheet

    return CollectionSheet.objects.filter(branch_id__in=filters.branch_ids).select_related(
        "branch", "center", "field_officer", "group"
    ).annotate(
        due=ExpressionWrapper(
            Coalesce(Sum("items__expected_installment"), Value(ZERO), output_field=MONEY)
            + Coalesce(Sum("items__expected_overdue"), Value(ZERO), output_field=MONEY)
            + Coalesce(Sum("items__expected_penalty"), Value(ZERO), output_field=MONEY)
            + Coalesce(Sum("items__expected_savings"), Value(ZERO), output_field=MONEY),
            output_field=MONEY,
        ),
        collected=ExpressionWrapper(
            Coalesce(Sum("items__collected_amount"), Value(ZERO), output_field=MONEY)
            + Coalesce(Sum("items__savings_amount"), Value(ZERO), output_field=MONEY),
            output_field=MONEY,
        ),
    )


def _collection_summary(request, filters):
    from core.collections.models import CollectionSheet

    queryset = _collection_sheets(filters)
    if not filters.status:
        queryset = queryset.filter(status=CollectionSheet.STATUS_POSTED)
    return _date_status_filters(
        queryset, REPORTS_BY_SLUG["collection-summary"], filters
    )


def _collection_register(request, filters):
    return _date_status_filters(
        _collection_sheets(filters),
        REPORTS_BY_SLUG["collection-register"],
        filters,
    )


def _collection_performance(request, filters):
    from core.collections.models import CollectionSheet

    queryset = CollectionSheet.objects.filter(
        branch_id__in=filters.branch_ids
    )
    if not filters.status:
        queryset = queryset.filter(status=CollectionSheet.STATUS_POSTED)
    queryset = _date_status_filters(
        queryset, REPORTS_BY_SLUG["collector-performance"], filters
    )
    return queryset.values(
        "field_officer__full_name", "branch__name"
    ).annotate(
        sheet_count=Count("pk"),
        due=Coalesce(
            Sum("items__expected_installment")
            + Sum("items__expected_overdue")
            + Sum("items__expected_penalty")
            + Sum("items__expected_savings"),
            Value(ZERO),
            output_field=MONEY,
        ),
        collected=Coalesce(
            Sum("items__collected_amount") + Sum("items__savings_amount"),
            Value(ZERO),
            output_field=MONEY,
        ),
    ).order_by("field_officer__full_name", "branch__name")


def _collection_efficiency(request, filters):
    from core.collections.models import CollectionSheet

    queryset = _collection_register(request, filters)
    if not filters.status:
        queryset = queryset.filter(status=CollectionSheet.STATUS_POSTED)
    return queryset.annotate(
        efficiency=Case(
            When(due__gt=ZERO, then=F("collected") * Value(100) / F("due")),
            default=Value(ZERO),
            output_field=DecimalField(max_digits=9, decimal_places=2),
        )
    )


def _collection_variances(request, filters):
    from core.collections.models import CollectionSheet

    queryset = _collection_register(request, filters)
    if not filters.status:
        queryset = queryset.filter(status=CollectionSheet.STATUS_POSTED)
    return _date_status_filters(
        queryset, REPORTS_BY_SLUG["shortage-excess"], filters
    )


def _access_review(request, filters):
    from core.accounts.models import UserRole

    queryset = UserRole.objects.filter(
        user__branch_id__in=filters.branch_ids,
    )
    if filters.status == "active":
        queryset = queryset.filter(user__is_active=True)
    elif filters.status == "inactive":
        queryset = queryset.filter(user__is_active=False)
    return queryset.select_related("user", "user__branch", "role").values(
        "user__username", "user__first_name", "user__last_name",
        "user__branch__name", "role__name",
    ).order_by("user__branch__name", "user__username")


def _role_permission_history(request, filters):
    from core.audit.models import AuditLog

    return AuditLog.objects.filter(
        branch_id__in=filters.branch_ids,
        entity_name__in=("Role", "Permission", "RolePermission", "UserRole"),
    ).select_related("branch").order_by("-timestamp_utc")


def _privileged_actions(request, filters):
    from core.audit.models import AuditLog

    return AuditLog.objects.filter(
        branch_id__in=filters.branch_ids,
    ).filter(
        Q(action__in=(
            "Approve", "Disburse", "WriteOff", "Reverse", "ReopenBusinessDay",
            "Export", "Download", "ViewSensitiveData", "Lockout",
        ))
        | Q(entity_name="HTTPMutation", action="RequestMutation")
    ).order_by("-timestamp_utc")


def _failed_logins(request, filters):
    from core.audit.models import AuditLog

    return AuditLog.objects.filter(
        branch_id__in=filters.branch_ids,
        action__in=("LoginFailed", "Lockout"),
    ).order_by("-timestamp_utc")


def _reopened_and_reversed(request, filters):
    from core.audit.models import AuditLog

    return AuditLog.objects.filter(
        branch_id__in=filters.branch_ids,
    ).filter(
        Q(action="ReopenBusinessDay", entity_name="BranchClosedDay")
        | Q(action__icontains="revers", entity_name__icontains="reversal")
        | Q(action__icontains="revers", entity_name__icontains="payment")
    ).order_by("-timestamp_utc")


def _kyc_completeness(request, filters):
    from django.db.models import Exists, OuterRef

    from core.branch.models import Member, MemberKYC

    verified = MemberKYC.objects.filter(
        member_id=OuterRef("pk"),
        status=MemberKYC.STATUS_VERIFIED,
        document_type=MemberKYC.DOC_TYPE_NATIONAL_ID,
    )
    members = Member.objects.filter(
        branch_id__in=filters.branch_ids
    ).select_related("branch").annotate(
        has_verified_kyc=Exists(verified)
    )
    if filters.status:
        members = members.filter(status=filters.status)
    if filters.start_date:
        members = members.filter(created_at__date__gte=filters.start_date)
    members = members.filter(created_at__date__lte=filters.end_date)
    return members.values("branch__name").annotate(
        member_count=Count("pk"),
        complete_count=Count("pk", filter=Q(has_verified_kyc=True)),
        incomplete_count=Count("pk", filter=Q(has_verified_kyc=False)),
    ).order_by("branch__name")


def _columns(*items):
    return tuple(ReportColumn(*item) for item in items)


REPORTS = (
    ReportDefinition(
        "trial-balance", "Trial balance", "Financial",
        "Module_Reports_trial_balance",
        _columns(
            ("account", "Account", "account__name"),
            ("opening_debit", "Opening debit"),
            ("opening_credit", "Opening credit"),
            ("debit", "Debit"),
            ("credit", "Credit"),
            ("closing_debit", "Closing debit"),
            ("closing_credit", "Closing credit"),
        ),
        _trial_balance,
        ("opening_debit", "opening_credit", "debit", "credit", "closing_debit", "closing_credit"),
    ),
    ReportDefinition(
        "general-ledger", "General ledger", "Financial",
        "Module_Reports_general_ledger",
        _columns(
            ("date", "Date", "entry__journal_date"),
            ("voucher", "Voucher", "entry__voucher_number"),
            ("branch", "Branch", "entry__branch__name"),
            ("account", "Account", "account__name"),
            ("narration", "Narration", "entry__narration"),
            ("debit", "Debit"),
            ("credit", "Credit"),
        ),
        _general_ledger, ("debit", "credit"), date_field="entry__journal_date",
    ),
    ReportDefinition(
        "cash-book", "Cash book", "Financial", "Module_Reports_cash_book",
        _columns(
            ("date", "Date", "entry__journal_date"),
            ("voucher", "Voucher", "entry__voucher_number"),
            ("account", "Account", "account__name"),
            ("narration", "Narration", "entry__narration"),
            ("receipt", "Receipt", "debit"),
            ("payment", "Payment", "credit"),
        ),
        _cash_book, ("receipt", "payment"), date_field="entry__journal_date",
    ),
    ReportDefinition(
        "income-statement", "Income statement", "Financial",
        "Module_Reports_income_statement",
        _columns(
            ("code", "Account code", "account__code"),
            ("account", "Account", "account__name"),
            ("account_type", "Type", "account__account_type"),
            ("debit", "Debit"),
            ("credit", "Credit"),
            ("amount", "Net income / (expense)"),
        ),
        _income_statement, ("debit", "credit", "amount"), date_field="entry__journal_date",
    ),
    ReportDefinition(
        "balance-sheet", "Balance sheet", "Financial",
        "Module_Reports_balance_sheet",
        _columns(
            ("code", "Account code"),
            ("account", "Account"),
            ("account_type", "Type"),
            ("amount", "Balance"),
        ),
        _balance_sheet, ("amount",),
    ),
    ReportDefinition(
        "receipts-payments", "Receipts and payments", "Financial",
        "Module_Reports_receipts_payments",
        _columns(
            ("date", "Date", "entry__journal_date"),
            ("voucher", "Voucher", "entry__voucher_number"),
            ("account", "Cash / bank account", "account__name"),
            ("narration", "Narration", "entry__narration"),
            ("receipts", "Receipts", "debit"),
            ("payments", "Payments", "credit"),
        ),
        _receipts_payments, ("receipts", "payments"), date_field="entry__journal_date",
    ),
    ReportDefinition(
        "disbursement-register", "Disbursement register", "Loan",
        "Module_Reports_disbursement_register",
        _columns(
            ("date", "Disbursed", "disbursed_at"),
            ("branch", "Branch", "branch__name"),
            ("member", "Member", "member__full_name"),
            ("member_code", "Member code", "member__member_code"),
            ("product", "Product", "product__name"),
            ("principal", "Principal"),
            ("status", "Status"),
        ),
        _disbursement_register, ("principal",),
        center_field="member__center_id",
        officer_field="member__center__field_officer_id",
        date_field="disbursed_at", status_field="status",
    ),
    ReportDefinition(
        "outstanding-loans", "Outstanding loans", "Loan",
        "Module_Reports_outstanding_loans",
        _columns(
            ("branch", "Branch", "branch__name"),
            ("member", "Member", "member__full_name"),
            ("loan_id", "Loan", "pk"),
            ("principal", "Principal"),
            ("outstanding", "Outstanding principal", "outstanding_principal"),
            ("disbursed", "Disbursed", "disbursed_at"),
        ),
        _outstanding_loans, ("principal", "outstanding"),
        center_field="member__center_id",
        officer_field="member__center__field_officer_id",
        date_field="disbursed_at", status_field="status",
    ),
    ReportDefinition(
        "overdue-loans", "Overdue loans", "Loan",
        "Module_Reports_overdue_loans",
        _columns(
            ("due_date", "Due date", "due_date"),
            ("loan_id", "Loan", "loan_id"),
            ("member", "Member", "loan__member__full_name"),
            ("branch", "Branch", "loan__branch__name"),
            ("remaining", "Overdue amount"),
        ),
        _overdue_installments, ("remaining",), center_field="loan__member__center_id",
        officer_field="loan__member__center__field_officer_id",
        date_field="due_date",
    ),
    ReportDefinition(
        "aging", "Loan aging", "Loan", "Module_Reports_aging",
        _columns(
            ("member", "Member", "loan__member__full_name"),
            ("loan_id", "Loan", "loan_id"),
            ("due_date", "Oldest due date", "due_date"),
            ("days", "Days past due", "days_past_due"),
            ("bucket", "Aging bucket", "aging_bucket"),
            ("amount", "Overdue amount", "remaining"),
        ),
        _loan_aging, ("amount",), center_field="loan__member__center_id",
        officer_field="loan__member__center__field_officer_id",
        date_field="due_date",
    ),
    ReportDefinition(
        "write-offs", "Loan write-offs", "Loan", "Module_Reports_write_offs",
        _columns(
            ("member", "Member", "member__full_name"),
            ("loan_id", "Loan", "pk"),
            ("date", "Closed date", "closed_at"),
            ("amount", "Written-off amount", "written_off_amount"),
            ("recovered", "Recovered", "recovered_amount"),
            ("reason", "Reason", "write_off_reason"),
        ),
        _writeoffs, ("amount", "recovered"),
        center_field="member__center_id",
        officer_field="member__center__field_officer_id",
        date_field="closed_at", status_field="status",
    ),
    ReportDefinition(
        "repayment-schedule", "Repayment schedule", "Loan",
        "Module_Reports_repayment_schedule",
        _columns(
            ("member", "Member", "loan__member__full_name"),
            ("loan_id", "Loan", "loan_id"),
            ("installment", "Installment", "number"),
            ("due_date", "Due date"),
            ("principal", "Principal due", "principal_due"),
            ("interest", "Interest due", "interest_due"),
            ("fee", "Fee due", "fee_due"),
        ),
        _repayment_schedule, ("principal", "interest", "fee"),
        center_field="loan__member__center_id",
        officer_field="loan__member__center__field_officer_id",
        date_field="due_date",
    ),
    ReportDefinition(
        "portfolio-at-risk", "Portfolio at risk", "Loan",
        "Module_Reports_portfolio_at_risk",
        _columns(
            ("threshold", "PAR threshold (days)"),
            ("amount", "At-risk principal"),
            ("percentage", "PAR percentage"),
            ("portfolio", "Portfolio outstanding"),
        ),
        _portfolio_at_risk,
    ),
    ReportDefinition(
        "loan-statement", "Loan statement", "Loan",
        "Module_Reports_loan_statement",
        _columns(
            ("date", "Payment date", "payment_date"),
            ("loan", "Loan", "loan_id"),
            ("member", "Member", "loan__member__full_name"),
            ("amount", "Payment amount"),
            ("principal", "Principal paid", "principal_paid"),
            ("interest", "Interest paid", "interest_paid"),
            ("fees", "Fees paid", "fee_paid"),
            ("penalties", "Penalties paid", "penalty_paid"),
            ("overpayment", "Overpayment", "overpayment_amount"),
        ),
        _loan_statement, ("amount", "principal", "interest", "fees", "penalties", "overpayment"),
        center_field="loan__member__center_id",
        officer_field="loan__member__center__field_officer_id",
        date_field="payment_date", status_field="loan__status",
    ),
    ReportDefinition(
        "classification", "Loan classification", "Loan",
        "Module_Reports_classification",
        _columns(
            ("class", "Class"),
            ("days", "Days past due"),
            ("loan_count", "Loans"),
            ("principal", "Outstanding principal"),
            ("provision_rate", "Provision rate"),
            ("provision", "Provision"),
        ),
        _classification, ("loan_count", "principal", "provision"),
    ),
    ReportDefinition(
        "account-list", "Savings account list", "Savings",
        "Module_Reports_account_list",
        _columns(
            ("account_number", "Account", "account_number"),
            ("branch", "Branch", "branch__name"),
            ("member", "Member", "member__full_name"),
            ("product", "Product", "product__name"),
            ("status", "Status"),
            ("balance", "Balance"),
        ),
        _savings_account_list, ("balance",),
        date_field="opened_at", status_field="status",
    ),
    ReportDefinition(
        "transaction-register", "Savings transaction register", "Savings",
        "Module_Reports_transaction_register",
        _columns(
            ("date", "Date", "transaction_date"),
            ("branch", "Branch", "branch__name"),
            ("account", "Account", "account__account_number"),
            ("member", "Member", "account__member__full_name"),
            ("type", "Type", "transaction_type"),
            ("status", "Status"),
            ("amount", "Amount"),
            ("balance", "Balance after", "balance_after"),
        ),
        _savings_transactions, ("amount",),
        date_field="transaction_date", status_field="status",
    ),
    ReportDefinition(
        "balance-summary", "Savings balance summary", "Savings",
        "Module_Reports_balance_summary",
        _columns(
            ("branch", "Branch", "branch__name"),
            ("product", "Product", "product__name"),
            ("status", "Status"),
            ("accounts", "Accounts", "account_count"),
            ("balance", "Balance"),
            ("reserved", "Reserved"),
            ("available", "Available"),
        ),
        _savings_summary, ("accounts", "balance", "reserved", "available"),
        status_field="status",
    ),
    ReportDefinition(
        "interest-posted", "Savings interest posted", "Savings",
        "Module_Reports_interest_posted",
        _columns(
            ("date", "Date", "transaction_date"),
            ("account", "Account", "account__account_number"),
            ("member", "Member", "account__member__full_name"),
            ("amount", "Interest", "amount"),
            ("gross", "Gross interest", "gross_amount"),
            ("tax", "Tax", "tax_amount"),
        ),
        _interest_posted, ("amount", "gross", "tax"),
        center_field="account__member__center_id",
        officer_field="account__member__center__field_officer_id",
        date_field="transaction_date",
    ),
    ReportDefinition(
        "dormant-accounts", "Dormant savings accounts", "Savings",
        "Module_Reports_dormant_accounts",
        _columns(
            ("account", "Account", "account_number"),
            ("branch", "Branch", "branch__name"),
            ("member", "Member", "member__full_name"),
            ("product", "Product", "product__name"),
            ("balance", "Balance"),
            ("opened", "Opened", "opened_at"),
        ),
        _dormant_accounts, ("balance",),
        date_field="opened_at", status_field="status",
    ),
    ReportDefinition(
        "member-list", "Member list", "Member", "Module_Reports_member_list",
        _columns(
            ("code", "Member code", "member_code"),
            ("name", "Member", "full_name"),
            ("branch", "Branch", "branch__name"),
            ("center", "Center", "center__name"),
            ("officer", "Field officer", "center__field_officer__full_name"),
            ("admission", "Admission date", "admission_date"),
            ("status", "Status"),
        ),
        _member_list, center_field="center_id",
        officer_field="center__field_officer_id",
        date_field="admission_date", status_field="status",
    ),
    ReportDefinition(
        "new-members", "New members", "Member", "Module_Reports_new_members",
        _columns(
            ("code", "Member code", "member_code"),
            ("name", "Member", "full_name"),
            ("branch", "Branch", "branch__name"),
            ("center", "Center", "center__name"),
            ("admission", "Admission date", "admission_date"),
        ),
        _new_members, center_field="center_id",
        officer_field="center__field_officer_id",
        date_field="admission_date", status_field="status",
    ),
    ReportDefinition(
        "status-summary", "Member status summary", "Member",
        "Module_Reports_status_summary",
        _columns(
            ("branch", "Branch", "branch__name"),
            ("status", "Status"),
            ("members", "Members", "member_count"),
        ),
        _member_status_summary, ("members",), center_field="center_id",
        officer_field="center__field_officer_id", date_field="admission_date",
        status_field="status",
    ),
    ReportDefinition(
        "kyc-pending-expired", "KYC pending or expired", "Member",
        "Module_Reports_kyc_pending_expired",
        _columns(
            ("member", "Member", "member__full_name"),
            ("code", "Member code", "member__member_code"),
            ("branch", "Branch", "member__branch__name"),
            ("document", "Document", "document_type"),
            ("status", "Status"),
            ("expiry", "Expiry date", "expiry_date"),
        ),
        _kyc_report, center_field="member__center_id",
        officer_field="member__center__field_officer_id",
        date_field="uploaded_at__date", status_field="status",
    ),
    ReportDefinition(
        "member-statement", "Member statement", "Member",
        "Module_Reports_member_statement",
        _columns(
            ("date", "Date"),
            ("code", "Member code", "member_code"),
            ("member", "Member"),
            ("type", "Module"),
            ("description", "Description"),
            ("debit", "Debit"),
            ("credit", "Credit"),
        ),
        _member_statement, ("debit", "credit"),
    ),
    ReportDefinition(
        "collection-summary", "Daily collection summary", "Collection",
        "Module_Reports_collection_summary",
        _columns(
            ("date", "Date", "collection_date"),
            ("branch", "Branch", "branch__name"),
            ("center", "Center", "center__name"),
            ("officer", "Field officer", "field_officer__full_name"),
            ("due", "Due"),
            ("collected", "Collected"),
            ("shortage", "Shortage", "cash_shortage"),
            ("excess", "Excess", "cash_excess"),
        ),
        _collection_summary, ("due", "collected", "shortage", "excess"),
        center_field="center_id", officer_field="field_officer_id",
        date_field="collection_date", status_field="status",
    ),
    ReportDefinition(
        "collection-register", "Collection sheet register", "Collection",
        "Module_Reports_collection_register",
        _columns(
            ("date", "Date", "collection_date"),
            ("branch", "Branch", "branch__name"),
            ("center", "Center", "center__name"),
            ("officer", "Field officer", "field_officer__full_name"),
            ("status", "Status"),
            ("due", "Due"),
            ("collected", "Collected"),
        ),
        _collection_register, ("due", "collected"),
        center_field="center_id", officer_field="field_officer_id",
        date_field="collection_date", status_field="status",
    ),
    ReportDefinition(
        "collector-performance", "Collector performance", "Collection",
        "Module_Reports_collector_performance",
        _columns(
            ("officer", "Field officer", "field_officer__full_name"),
            ("branch", "Branch", "branch__name"),
            ("sheets", "Sheets", "sheet_count"),
            ("due", "Due"),
            ("collected", "Collected"),
        ),
        _collection_performance, ("sheets", "due", "collected"),
        center_field="center_id", officer_field="field_officer_id",
        date_field="collection_date", status_field="status",
    ),
    ReportDefinition(
        "collection-efficiency", "Collection efficiency", "Collection",
        "Module_Reports_collection_efficiency",
        _columns(
            ("date", "Date", "collection_date"),
            ("center", "Center", "center__name"),
            ("officer", "Field officer", "field_officer__full_name"),
            ("due", "Due"),
            ("collected", "Collected"),
            ("efficiency", "Efficiency"),
        ),
        _collection_efficiency, ("due", "collected"),
        center_field="center_id", officer_field="field_officer_id",
        date_field="collection_date", status_field="status",
    ),
    ReportDefinition(
        "shortage-excess", "Collection shortage and excess", "Collection",
        "Module_Reports_shortage_excess",
        _columns(
            ("date", "Date", "collection_date"),
            ("center", "Center", "center__name"),
            ("officer", "Field officer", "field_officer__full_name"),
            ("cash_received", "Cash received"),
            ("shortage", "Shortage", "cash_shortage"),
            ("excess", "Excess", "cash_excess"),
        ),
        _collection_variances, ("cash_received", "shortage", "excess"),
        center_field="center_id", officer_field="field_officer_id",
        date_field="collection_date", status_field="status",
    ),
    ReportDefinition(
        "user-access-review", "User access review", "Compliance",
        "Module_Reports_user_access_review",
        _columns(
            ("username", "Username", "user__username"),
            ("first_name", "First name", "user__first_name"),
            ("last_name", "Last name", "user__last_name"),
            ("branch", "Branch", "user__branch__name"),
            ("role", "Role", "role__name"),
        ),
        _access_review,
    ),
    ReportDefinition(
        "role-permission-history", "Role and permission change history", "Compliance",
        "Module_Reports_role_permission_history",
        _columns(
            ("date", "Changed at", "timestamp_utc"),
            ("user", "Changed by", "user_name"),
            ("action", "Action"),
            ("entity", "Entity", "entity_name"),
            ("entity_id", "Record", "entity_id"),
            ("old_values", "Before", "old_values"),
            ("new_values", "After", "new_values"),
        ),
        _role_permission_history, date_field="timestamp_utc",
    ),
    ReportDefinition(
        "privileged-actions", "Privileged actions", "Compliance",
        "Module_Reports_privileged_actions",
        _columns(
            ("date", "Time", "timestamp_utc"),
            ("user", "User", "user_name"),
            ("action", "Action"),
            ("entity", "Entity", "entity_name"),
            ("entity_id", "Record", "entity_id"),
            ("branch", "Branch", "branch__name"),
        ),
        _privileged_actions, date_field="timestamp_utc",
    ),
    ReportDefinition(
        "failed-logins", "Failed logins and lockouts", "Compliance",
        "Module_Reports_failed_logins",
        _columns(
            ("date", "Time", "timestamp_utc"),
            ("user", "Username", "user_name"),
            ("action", "Event"),
            ("ip", "IP address", "ip_address"),
            ("branch", "Branch", "branch__name"),
        ),
        _failed_logins, date_field="timestamp_utc",
    ),
    ReportDefinition(
        "day-reopen-reversals", "Reopened days and reversals", "Compliance",
        "Module_Reports_day_reopen_reversals",
        _columns(
            ("date", "Time", "timestamp_utc"),
            ("user", "User", "user_name"),
            ("action", "Action"),
            ("entity", "Entity", "entity_name"),
            ("entity_id", "Record", "entity_id"),
            ("reason", "Reason", "remarks"),
        ),
        _reopened_and_reversed, date_field="timestamp_utc",
    ),
    ReportDefinition(
        "kyc-completeness", "KYC completeness", "Compliance",
        "Module_Reports_kyc_completeness",
        _columns(
            ("branch", "Branch", "branch__name"),
            ("member_count", "Members"),
            ("complete_count", "Verified identity"),
            ("incomplete_count", "Missing verified identity"),
        ),
        _kyc_completeness, ("member_count", "complete_count", "incomplete_count"),
    ),
)

REPORTS_BY_SLUG = {report.slug: report for report in REPORTS}
REPORTS_BY_ROUTE = {report.route_name: report for report in REPORTS}
