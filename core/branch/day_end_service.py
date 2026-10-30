from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from core.accounting.models import JournalEntry, JournalLine, SystemAccountMapping
from core.audit.services import log_action
from core.collections.models import CollectionSheet

from .models import Branch, BranchClosedDay, BranchHoliday


class BranchDayService:
    def __init__(self, request):
        self.request = request

    def _branch(self, branch_id, *, lock=False):
        branches = Branch.unscoped
        if lock:
            branches = branches.select_for_update()
        branch = branches.filter(pk=branch_id, is_active=True).first()
        if branch is None:
            raise Branch.DoesNotExist
        user = self.request.user
        if branch.pk not in user.accessible_branch_ids(
            getattr(self.request, "active_branch_id", None)
        ):
            raise PermissionDenied("You cannot access this branch.")
        if not (
            user.is_superuser
            or Branch.unscoped.filter(
                pk=branch.pk, branch_manager__user_id=user.pk
            ).exists()
        ):
            raise PermissionDenied("Only the branch manager can close or reopen its business day.")
        return branch

    @staticmethod
    def assert_open(branch_id, business_date):
        closed = BranchClosedDay.objects.filter(
            branch_id=branch_id, business_date=business_date, is_closed=True
        ).exists()
        if closed:
            raise ValidationError(
                f"Business date {business_date} is closed for branch {branch_id}; reopen it before posting."
            )

    def checklist(self, *, branch_id, business_date=None):
        branch = self._branch(branch_id)
        selected_date = business_date or branch.business_date
        sheets = CollectionSheet.objects.filter(
            branch=branch, collection_date=selected_date
        )
        incomplete_sheets = sheets.exclude(
            status__in=[
                CollectionSheet.STATUS_POSTED,
                CollectionSheet.STATUS_REVERSED,
                CollectionSheet.STATUS_CANCELLED,
            ]
        ).count()
        pending_journals = JournalEntry.objects.filter(
            branch=branch,
            journal_date=selected_date,
            status=JournalEntry.STATUS_PENDING,
        ).count()
        from core.savings.models import SavingsTransaction

        pending_savings = SavingsTransaction.objects.filter(
            branch=branch,
            transaction_date=selected_date,
            status=SavingsTransaction.STATUS_PENDING,
        ).count()
        mapping = SystemAccountMapping.objects.filter(
            key="cash_in_hand", account__is_active=True
        ).select_related("account").first()
        if mapping is None:
            raise ValidationError(
                'Configure an active "cash_in_hand" system-account mapping before day-end.'
            )
        totals = JournalLine.objects.filter(
            entry__branch=branch,
            entry__status=JournalEntry.STATUS_POSTED,
            entry__journal_date__lte=selected_date,
            account=mapping.account,
        ).aggregate(debits=Sum("debit"), credits=Sum("credit"))
        cash_book = (totals["debits"] or Decimal("0.00")) - (
            totals["credits"] or Decimal("0.00")
        )
        return {
            "branch": branch,
            "business_date": selected_date,
            "incomplete_sheets": incomplete_sheets,
            "pending_approvals": pending_journals + pending_savings,
            "cash_book": cash_book,
            "can_close": selected_date == branch.business_date
            and incomplete_sheets == 0,
        }

    @transaction.atomic
    def close(
        self,
        *,
        branch_id,
        cash_count,
        cash_difference_reason="",
        carryover_note="",
    ):
        branch = self._branch(branch_id, lock=True)
        business_date = branch.business_date
        summary = self.checklist(branch_id=branch.pk, business_date=business_date)
        if summary["incomplete_sheets"]:
            raise ValidationError(
                f"{summary['incomplete_sheets']} collection sheet(s) are not Posted, Reversed, or Cancelled."
            )
        if summary["pending_approvals"] and not carryover_note.strip():
            raise ValidationError(
                f"{summary['pending_approvals']} approval(s) remain; clear them or enter a carry-over note."
            )
        if not isinstance(cash_count, Decimal) or not cash_count.is_finite() or cash_count < 0:
            raise ValidationError({"cash_count": "Enter a non-negative cash count."})
        if cash_count != summary["cash_book"] and not cash_difference_reason.strip():
            raise ValidationError(
                {"cash_difference_reason": "Explain the difference between cash counted and the cash book."}
            )
        closed_day = BranchClosedDay.objects.filter(
            branch=branch, business_date=business_date
        ).first()
        if closed_day and closed_day.is_closed:
            raise ValidationError("This business date is already closed.")
        if closed_day:
            closed_day.is_closed = True
            closed_day.cash_count = cash_count
            closed_day.cash_difference_reason = cash_difference_reason.strip()
            closed_day.carryover_note = carryover_note.strip()
            closed_day.closed_by = self.request.user
            closed_day.closed_at = timezone.now()
            closed_day.reopened_by = None
            closed_day.reopened_at = None
            closed_day.reopen_reason = ""
            closed_day.save()
        else:
            closed_day = BranchClosedDay.objects.create(
                branch=branch,
                business_date=business_date,
                cash_count=cash_count,
                cash_difference_reason=cash_difference_reason.strip(),
                carryover_note=carryover_note.strip(),
                closed_by=self.request.user,
            )
        next_date = business_date + timedelta(days=1)
        while next_date.weekday() >= 5 or BranchHoliday.objects.filter(
            branch=branch, date=next_date, is_active=True
        ).exists():
            next_date += timedelta(days=1)
        Branch.unscoped.filter(pk=branch.pk).update(
            business_date=next_date, updated_at=timezone.now()
        )
        branch.business_date = next_date
        log_action(
            "CloseBusinessDay",
            "BranchClosedDay",
            closed_day.pk,
            old_values={"business_date": str(business_date)},
            new_values={
                "business_date": str(business_date),
                "next_business_date": str(next_date),
                "cash_count": str(cash_count),
                "cash_book": str(summary["cash_book"]),
            },
            remarks="; ".join(
                value for value in (carryover_note.strip(), cash_difference_reason.strip()) if value
            ),
            branch_id=branch.pk,
        )
        return closed_day

    @transaction.atomic
    def reopen(self, *, branch_id, business_date, reason):
        branch = self._branch(branch_id, lock=True)
        if not reason.strip():
            raise ValidationError({"reason": "A reason is required to reopen a business date."})
        closed_day = BranchClosedDay.objects.select_for_update().filter(
            branch=branch, business_date=business_date, is_closed=True
        ).first()
        if closed_day is None:
            raise ValidationError("The selected business date is not closed.")
        closed_day.is_closed = False
        closed_day.reopened_by = self.request.user
        closed_day.reopened_at = timezone.now()
        closed_day.reopen_reason = reason.strip()
        closed_day.save(
            update_fields=[
                "is_closed",
                "reopened_by",
                "reopened_at",
                "reopen_reason",
            ]
        )
        if business_date < branch.business_date:
            Branch.unscoped.filter(pk=branch.pk).update(
                business_date=business_date, updated_at=timezone.now()
            )
            branch.business_date = business_date
        log_action(
            "ReopenBusinessDay",
            "BranchClosedDay",
            closed_day.pk,
            old_values={"is_closed": True},
            new_values={"is_closed": False},
            remarks=reason.strip(),
            branch_id=branch.pk,
        )
        return closed_day
