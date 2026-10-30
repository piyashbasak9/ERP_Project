import uuid
from decimal import Decimal, InvalidOperation

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from core.accounting.models import SystemAccountMapping
from core.accounting.services import JournalService
from core.audit.services import log_action
from core.branch.models import Branch, Center, Group, Member, Staff
from core.loans.models import Loan, LoanInstallment
from core.loans.services import LoanService
from core.savings.models import SavingsAccount, SavingsTransaction
from core.savings.services import SavingsService

from .models import (
    CollectionPosting,
    CollectionPostingReversal,
    CollectionSheet,
    CollectionSheetItem,
    CollectionSheetReversal,
    CollectionSheetReversalApproval,
)

ZERO = Decimal("0.00")


class CollectionService:
    def __init__(self, request):
        self.request = request

    def _ensure_access(self, branch_id):
        user = self.request.user
        if (
            not user.is_authenticated
            or not user.is_active
            or branch_id
            not in user.accessible_branch_ids(
                getattr(self.request, "active_branch_id", None)
            )
        ):
            raise PermissionDenied("You cannot access this collection sheet.")

    def _is_manager(self, branch_id):
        user = self.request.user
        return user.is_superuser or Branch.unscoped.filter(
            pk=branch_id, branch_manager__user_id=user.pk
        ).exists()

    def _can_collect(self, sheet):
        self._ensure_access(sheet.branch_id)
        if self._is_manager(sheet.branch_id):
            return
        if sheet.field_officer.user_id != self.request.user.pk:
            raise PermissionDenied("Only the center field officer or branch manager can enter collections.")

    @transaction.atomic
    def generate(
        self,
        *,
        center_id,
        collection_date,
        idempotency_key,
        group_id=None,
        field_officer_id=None,
    ):
        key = self._uuid(idempotency_key)
        replay = CollectionSheet.unscoped.select_for_update().filter(
            generated_by=self.request.user, idempotency_key=key
        ).first()
        if replay:
            if (
                replay.center_id != center_id
                or replay.collection_date != collection_date
                or replay.group_id != group_id
                or (
                    field_officer_id is not None
                    and replay.field_officer_id != field_officer_id
                )
            ):
                raise ValidationError(
                    {"idempotency_key": "This key was already used with different sheet details."}
                )
            self._ensure_access(replay.branch_id)
            return replay

        center = Center.unscoped.select_for_update().filter(
            pk=center_id, is_active=True
        ).first()
        if center is None:
            raise ValidationError({"center": "Select an active center."})
        self._ensure_access(center.branch_id)
        field_officer = Staff.unscoped.filter(
            pk=field_officer_id or center.field_officer_id,
            branch_id=center.branch_id,
            is_active=True,
        ).first()
        if field_officer is None or field_officer.user_id is None:
            raise ValidationError({"field_officer": "Select an active field officer with a user account."})
        if (
            center.field_officer_id != field_officer.pk
            and not field_officer.assigned_centers.filter(pk=center.pk).exists()
        ):
            raise ValidationError({"field_officer": "Assign the field officer to this center first."})
        if not self._is_manager(center.branch_id) and field_officer.user_id != self.request.user.pk:
            raise PermissionDenied("Only the center field officer or branch manager can generate this sheet.")
        group = None
        if group_id:
            group = Group.unscoped.filter(
                pk=group_id, center_id=center.pk, branch_id=center.branch_id, is_active=True
            ).first()
            if group is None:
                raise ValidationError({"group": "Select an active group in this center."})

        active_sheet = CollectionSheet.unscoped.select_for_update().filter(
            center=center,
            collection_date=collection_date,
        ).exclude(status=CollectionSheet.STATUS_CANCELLED).first()
        if active_sheet:
            if active_sheet.group_id != group_id or active_sheet.field_officer_id != field_officer.pk:
                raise ValidationError("An active collection sheet already exists for this center and date.")
            return active_sheet

        sheet = CollectionSheet(
            branch_id=center.branch_id,
            center=center,
            group=group,
            field_officer=field_officer,
            collection_date=collection_date,
            idempotency_key=key,
            generated_by=self.request.user,
        )
        sheet.full_clean()
        try:
            with transaction.atomic():
                sheet.save()
        except IntegrityError:
            existing = CollectionSheet.unscoped.filter(
                center=center,
                collection_date=collection_date,
            ).exclude(status=CollectionSheet.STATUS_CANCELLED).first()
            if existing is None:
                raise
            return existing

        member_query = Member.unscoped.filter(
            branch_id=center.branch_id, center_id=center.pk
        ).order_by("member_code")
        if group:
            member_query = member_query.filter(group_id=group.pk)
        loan_service = LoanService(self.request)
        for member in member_query:
            dues = {
                "installment": ZERO,
                "overdue": ZERO,
                "penalty": ZERO,
                "savings": ZERO,
            }
            loans = Loan.unscoped.filter(
                member=member, branch_id=center.branch_id, status=Loan.STATUS_ACTIVE
            ).order_by("disbursed_at", "pk")
            for loan in loans:
                loan_due = loan_service.collection_due(
                    loan_id=loan.pk, as_of_date=collection_date
                )
                dues["installment"] += loan_due["installment"]
                dues["overdue"] += loan_due["overdue"]
                dues["penalty"] += loan_due["penalty"]
                dues["savings"] += (
                    (loan_due["installment"] + loan_due["overdue"])
                    * loan.product_term("required_savings_rate")
                    / Decimal(100)
                )
            CollectionSheetItem.unscoped.create(
                branch_id=center.branch_id,
                sheet=sheet,
                member=member,
                expected_installment=dues["installment"],
                expected_overdue=dues["overdue"],
                expected_penalty=dues["penalty"],
                expected_savings=dues["savings"].quantize(Decimal("0.01")),
            )
        log_action(
            "Generate",
            "CollectionSheet",
            sheet.pk,
            new_values={
                "status": sheet.status,
                "center_id": center.pk,
                "group_id": group.pk if group else None,
                "collection_date": collection_date.isoformat(),
            },
            branch_id=center.branch_id,
        )
        return sheet

    @transaction.atomic
    def start(self, *, sheet_id):
        sheet = self._locked_sheet(sheet_id)
        self._can_collect(sheet)
        self._transition(
            sheet,
            CollectionSheet.STATUS_GENERATED,
            CollectionSheet.STATUS_IN_PROGRESS,
            "Start",
        )
        return sheet

    @transaction.atomic
    def record_collection(self, *, sheet_id, item_id, collected_amount, savings_amount, reason=""):
        sheet = self._locked_sheet(sheet_id)
        self._can_collect(sheet)
        if sheet.status != CollectionSheet.STATUS_IN_PROGRESS:
            raise ValidationError("Collection entries can only be changed while the sheet is in progress.")
        item = CollectionSheetItem.unscoped.select_for_update().filter(
            pk=item_id, sheet=sheet
        ).select_related("member").first()
        if item is None:
            raise CollectionSheetItem.DoesNotExist
        old_amount = item.collected_amount
        old_savings = item.savings_amount
        item.collected_amount = self._amount(collected_amount, "collected_amount")
        item.savings_amount = self._amount(savings_amount, "savings_amount")
        item.reason = reason.strip()
        item.updated_by = self.request.user
        item.full_clean()
        item.save(
            update_fields=[
                "collected_amount",
                "savings_amount",
                "reason",
                "updated_by",
                "updated_at",
            ]
        )
        log_action(
            "UpdateCollection",
            "CollectionSheetItem",
            item.pk,
            old_values={
                "collected_amount": str(old_amount),
                "savings_amount": str(old_savings),
            },
            new_values={
                "collected_amount": str(item.collected_amount),
                "savings_amount": str(item.savings_amount),
                "reason": item.reason,
            },
            branch_id=sheet.branch_id,
        )
        return item

    @transaction.atomic
    def submit(self, *, sheet_id):
        sheet = self._locked_sheet(sheet_id)
        self._can_collect(sheet)
        self._transition(
            sheet,
            CollectionSheet.STATUS_IN_PROGRESS,
            CollectionSheet.STATUS_SUBMITTED,
            "Submit",
        )
        sheet.submitted_by = self.request.user
        sheet.submitted_at = timezone.now()
        sheet.save(update_fields=["submitted_by", "submitted_at"])
        return sheet

    @transaction.atomic
    def reconcile(self, *, sheet_id, cash_received):
        sheet = self._locked_sheet(sheet_id)
        self._ensure_access(sheet.branch_id)
        if sheet.status != CollectionSheet.STATUS_SUBMITTED:
            raise ValidationError("Only submitted sheets can be reconciled.")
        if sheet.generated_by_id == self.request.user.pk or (
            sheet.field_officer.user_id == self.request.user.pk
        ):
            raise ValidationError("The sheet maker or collector cannot verify their own sheet.")
        cash_received = self._amount(cash_received, "cash_received")
        total_collected = self._sheet_total(sheet)
        sheet.cash_received = cash_received
        sheet.cash_shortage = max(ZERO, total_collected - cash_received)
        sheet.cash_excess = max(ZERO, cash_received - total_collected)
        sheet.status = CollectionSheet.STATUS_RECONCILED
        sheet.reconciled_by = self.request.user
        sheet.reconciled_at = timezone.now()
        sheet.full_clean()
        sheet.save(
            update_fields=[
                "status",
                "cash_received",
                "cash_shortage",
                "cash_excess",
                "reconciled_by",
                "reconciled_at",
            ]
        )
        log_action(
            "Reconcile",
            "CollectionSheet",
            sheet.pk,
            old_values={"status": CollectionSheet.STATUS_SUBMITTED},
            new_values={
                "status": sheet.status,
                "cash_received": str(cash_received),
                "shortage": str(sheet.cash_shortage),
                "excess": str(sheet.cash_excess),
            },
            branch_id=sheet.branch_id,
        )
        return sheet

    @transaction.atomic
    def post(self, *, sheet_id, idempotency_key):
        key = self._uuid(idempotency_key)
        sheet = self._locked_sheet(sheet_id)
        self._ensure_access(sheet.branch_id)
        if sheet.status == CollectionSheet.STATUS_POSTED:
            return sheet
        if sheet.status != CollectionSheet.STATUS_RECONCILED:
            raise ValidationError("Only reconciled sheets can be posted.")
        if CollectionSheet.unscoped.filter(posting_key=key).exclude(pk=sheet.pk).exists():
            raise ValidationError({"idempotency_key": "This key was already used to post another sheet."})
        items = list(
            CollectionSheetItem.unscoped.select_for_update()
            .filter(sheet=sheet)
            .select_related("member")
            .order_by("pk")
        )
        sheet.variance_journal = self._post_variance(sheet)
        if sheet.variance_journal_id:
            sheet.save(update_fields=["variance_journal"])
        loan_service = LoanService(self.request)
        savings_service = SavingsService(self.request)
        for item in items:
            self._post_item(
                sheet=sheet,
                item=item,
                key=key,
                loan_service=loan_service,
                savings_service=savings_service,
            )
        old_status = sheet.status
        sheet.status = CollectionSheet.STATUS_POSTED
        sheet.posting_key = key
        sheet.posted_by = self.request.user
        sheet.posted_at = timezone.now()
        sheet.full_clean()
        sheet.save(
            update_fields=["status", "posting_key", "posted_by", "posted_at"]
        )
        log_action(
            "Post",
            "CollectionSheet",
            sheet.pk,
            old_values={"status": old_status},
            new_values={
                "status": sheet.status,
                "total_collected": str(self._sheet_total(sheet)),
            },
            branch_id=sheet.branch_id,
        )
        return sheet

    @transaction.atomic
    def request_reversal(self, *, sheet_id, reversal_date, reason, idempotency_key):
        key = self._uuid(idempotency_key)
        sheet = self._locked_sheet(sheet_id)
        if sheet.status != CollectionSheet.STATUS_POSTED:
            raise ValidationError("Only posted collection sheets can be reversed.")
        if hasattr(sheet, "reversal_record"):
            reversal = sheet.reversal_record
            if (
                reversal.idempotency_key == key
                and reversal.reversal_date == reversal_date
                and reversal.reason == reason.strip()
            ):
                return reversal
            raise ValidationError("This collection sheet already has a reversal request.")
        if not reason.strip():
            raise ValidationError({"reason": "A reversal reason is required."})
        reversal = CollectionSheetReversal(
            sheet=sheet,
            reversal_date=reversal_date,
            idempotency_key=key,
            reason=reason.strip(),
            requested_by=self.request.user,
        )
        reversal.full_clean()
        reversal.save()
        log_action(
            "RequestReversal",
            "CollectionSheet",
            sheet.pk,
            new_values={"reversal_id": reversal.pk},
            remarks=reason.strip(),
            branch_id=sheet.branch_id,
        )
        return reversal

    @transaction.atomic
    def approve_reversal(self, *, reversal_id):
        reversal = CollectionSheetReversal.objects.select_for_update().filter(
            pk=reversal_id
        ).first()
        if reversal is None:
            raise CollectionSheetReversal.DoesNotExist
        sheet = self._locked_sheet(reversal.sheet_id)
        if reversal.status == CollectionSheetReversal.STATUS_COMPLETED:
            return reversal
        if reversal.requested_by_id == self.request.user.pk:
            raise ValidationError("The reversal requester cannot approve the reversal.")
        if sheet.status != CollectionSheet.STATUS_POSTED:
            raise ValidationError("Only a posted sheet can be reversed.")

        loan_service = LoanService(self.request)
        savings_service = SavingsService(self.request)
        postings = CollectionPosting.objects.filter(
            item__sheet=sheet
        ).order_by("-created_at", "-pk")
        for posting in postings:
            row = {
                "original_posting": posting,
                "sheet_reversal": reversal,
            }
            if posting.loan_payment_id:
                row["loan_payment_reversal"] = loan_service.reverse_payment(
                    payment_id=posting.loan_payment_id,
                    reversal_date=reversal.reversal_date,
                    reason=reversal.reason,
                )
            elif posting.savings_transaction_id:
                row["savings_transaction_reversal"] = savings_service.reverse(
                    transaction_id=posting.savings_transaction_id,
                    reversal_date=reversal.reversal_date,
                    reason=reversal.reason,
                )
            CollectionPostingReversal.objects.create(**row)

        variance_reversal = None
        if sheet.variance_journal_id:
            variance_reversal = JournalService(self.request).reverse(
                entry_id=sheet.variance_journal_id,
                reversal_date=reversal.reversal_date,
                reason=reversal.reason,
            )
        sheet.status = CollectionSheet.STATUS_REVERSED
        sheet._reversal_authorized = True
        try:
            sheet.save(update_fields=["status"])
        finally:
            del sheet._reversal_authorized
        CollectionSheetReversalApproval.objects.create(
            reversal=reversal,
            approved_by=self.request.user,
            variance_journal_reversal=variance_reversal,
        )
        log_action(
            "Reverse",
            "CollectionSheet",
            sheet.pk,
            old_values={"status": CollectionSheet.STATUS_POSTED},
            new_values={
                "status": CollectionSheet.STATUS_REVERSED,
                "reversal_id": reversal.pk,
            },
            remarks=reversal.reason,
            branch_id=sheet.branch_id,
        )
        return reversal

    @transaction.atomic
    def cancel(self, *, sheet_id, reason):
        sheet = self._locked_sheet(sheet_id)
        self._ensure_access(sheet.branch_id)
        if sheet.status not in {
            CollectionSheet.STATUS_GENERATED,
            CollectionSheet.STATUS_IN_PROGRESS,
        }:
            raise ValidationError("Only generated or in-progress sheets can be cancelled.")
        if not reason.strip():
            raise ValidationError({"reason": "A cancellation reason is required."})
        old_status = sheet.status
        sheet.status = CollectionSheet.STATUS_CANCELLED
        sheet.cancellation_reason = reason.strip()
        sheet.save(update_fields=["status", "cancellation_reason"])
        log_action(
            "Cancel",
            "CollectionSheet",
            sheet.pk,
            old_values={"status": old_status},
            new_values={"status": sheet.status},
            remarks=reason.strip(),
            branch_id=sheet.branch_id,
        )
        return sheet

    def _post_item(self, *, sheet, item, key, loan_service, savings_service):
        if item.collected_amount:
            active_loans = list(
                Loan.unscoped.select_for_update()
                .filter(
                    member_id=item.member_id,
                    branch_id=sheet.branch_id,
                    status=Loan.STATUS_ACTIVE,
                )
                .order_by("disbursed_at", "pk")
            )
            if not active_loans:
                raise ValidationError(
                    f"{item.member.member_code} has a collection amount but no active loan."
                )
            capacities = []
            for loan in active_loans:
                installments = list(
                    LoanInstallment.objects.select_for_update().filter(
                        loan=loan, schedule_version=loan.schedule_version
                    )
                )
                penalty = loan_service._assess_penalties(
                    loan, installments, sheet.collection_date
                )
                capacity = (
                    loan.outstanding_principal
                    + sum((row.interest_remaining for row in installments), ZERO)
                    + sum((row.fee_remaining for row in installments), ZERO)
                    + penalty
                )
                capacities.append((loan, capacity))
            remaining = item.collected_amount
            for index, (loan, capacity) in enumerate(capacities):
                if remaining <= ZERO:
                    break
                if index == len(capacities) - 1:
                    amount = remaining
                else:
                    amount = min(remaining, capacity)
                if amount <= ZERO:
                    continue
                payment_key = uuid.uuid5(key, f"collection-{sheet.pk}-{item.pk}-loan-{loan.pk}")
                payment = loan_service.repay(
                    loan_id=loan.pk,
                    amount=amount,
                    payment_date=sheet.collection_date,
                    idempotency_key=payment_key,
                    include_future=True,
                )
                posting = CollectionPosting(
                    branch_id=sheet.branch_id,
                    item=item,
                    kind=CollectionPosting.KIND_LOAN,
                    loan_payment=payment,
                    amount=amount,
                )
                posting.full_clean()
                posting.save()
                remaining -= amount
        if item.savings_amount:
            account = SavingsAccount.unscoped.select_for_update().filter(
                member_id=item.member_id,
                branch_id=sheet.branch_id,
                status=SavingsAccount.STATUS_ACTIVE,
            ).order_by("pk").first()
            if account is None:
                raise ValidationError(
                    f"{item.member.member_code} has no active savings account for this deposit."
                )
            savings_key = uuid.uuid5(key, f"collection-{sheet.pk}-{item.pk}-savings")
            savings_tx = savings_service.deposit(
                account_id=account.pk,
                amount=item.savings_amount,
                transaction_date=sheet.collection_date,
                payment_channel=SavingsTransaction.CHANNEL_CASH,
                idempotency_key=savings_key,
                narration=f"Collection sheet {sheet.pk}",
            )
            posting = CollectionPosting(
                branch_id=sheet.branch_id,
                item=item,
                kind=CollectionPosting.KIND_SAVINGS,
                savings_transaction=savings_tx,
                amount=item.savings_amount,
            )
            posting.full_clean()
            posting.save()

    def _post_variance(self, sheet):
        variance = sheet.cash_shortage or sheet.cash_excess
        if variance <= ZERO:
            return None
        shortage = sheet.cash_shortage > ZERO
        keys = (
            ("cash_shortage", "cash_in_hand")
            if shortage
            else ("cash_in_hand", "collection_excess_income")
        )
        mappings = [self._mapping(key) for key in keys]
        journal_service = JournalService(self.request)
        journal_key = uuid.uuid5(sheet.idempotency_key, f"collection-variance-{sheet.pk}")
        entry = journal_service.create_entry(
            branch_id=sheet.branch_id,
            journal_date=sheet.collection_date,
            narration=f"Cash {'shortage' if shortage else 'excess'} for collection sheet {sheet.pk}",
            source_type="collection_reconciliation",
            source_id=str(sheet.pk),
            idempotency_key=journal_key,
        )
        debit_account, credit_account = (
            mappings[0].account_id,
            mappings[1].account_id,
        )
        journal_service.add_line(
            entry_id=entry.pk,
            account_id=debit_account,
            debit=variance,
            narration="Collection cash variance",
        )
        journal_service.add_line(
            entry_id=entry.pk,
            account_id=credit_account,
            credit=variance,
            narration="Collection cash variance",
        )
        return journal_service.post(entry_id=entry.pk)

    @staticmethod
    def _mapping(key):
        mapping = SystemAccountMapping.objects.select_related("account").filter(
            key=key, account__is_active=True, account__allows_direct_posting=True
        ).first()
        if mapping is None:
            raise ValidationError(
                f'The system account "{key}" must be mapped to an active postable account first.'
            )
        expected = SystemAccountMapping.EXPECTED_ACCOUNT_TYPES[key]
        if mapping.account.account_type != expected:
            raise ValidationError(f'The system account "{key}" requires an {expected} account.')
        return mapping

    def _locked_sheet(self, sheet_id):
        sheet = CollectionSheet.unscoped.select_for_update().filter(pk=sheet_id).first()
        if sheet is None:
            raise CollectionSheet.DoesNotExist
        self._ensure_access(sheet.branch_id)
        return sheet

    @staticmethod
    def _sheet_total(sheet):
        return sheet.items.aggregate(
            total=Sum("collected_amount") + Sum("savings_amount")
        )["total"] or ZERO

    @staticmethod
    def _transition(sheet, expected, target, action):
        if sheet.status != expected:
            raise ValidationError(
                f"A sheet in {sheet.get_status_display()} cannot be {action.lower()}ed."
            )
        old_status = sheet.status
        sheet.status = target
        sheet.save(update_fields=["status"])
        log_action(
            action,
            "CollectionSheet",
            sheet.pk,
            old_values={"status": old_status},
            new_values={"status": target},
            branch_id=sheet.branch_id,
        )

    @staticmethod
    def _amount(value, field):
        try:
            amount = Decimal(str(value)).quantize(Decimal("0.01"))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValidationError({field: "Enter a valid monetary amount."}) from exc
        if not amount.is_finite() or amount < ZERO:
            raise ValidationError({field: "Enter a non-negative monetary amount."})
        return amount

    @staticmethod
    def _uuid(value):
        try:
            return uuid.UUID(str(value))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValidationError({"idempotency_key": "A valid idempotency key is required."}) from exc
