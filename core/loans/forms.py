import uuid
from decimal import Decimal

from django import forms
from django.utils import timezone

from core.branch.models import Branch, Member

from .models import LoanApplication, LoanProduct


class LoanProductForm(forms.ModelForm):
    class Meta:
        model = LoanProduct
        fields = [
            "code",
            "name",
            "interest_method",
            "annual_interest_rate",
            "min_amount",
            "max_amount",
            "min_term",
            "max_term",
            "installment_frequency",
            "processing_fee",
            "processing_fee_rate",
            "insurance_fee",
            "insurance_fee_rate",
            "grace_period_days",
            "late_penalty_rate",
            "penalty_grace_days",
            "penalty_frequency",
            "penalty_cap_rate",
            "required_savings_rate",
            "max_concurrent_loans",
            "cycle_limits",
            "approval_limit",
            "early_settlement_fee",
            "holiday_convention",
            "requires_verified_kyc",
            "is_active",
        ]
        widgets = {
            "code": forms.TextInput(attrs={"class": "form-control"}),
            "name": forms.TextInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if not isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", "form-control")


class LoanApplicationForm(forms.Form):
    branch = forms.ModelChoiceField(queryset=Branch.unscoped.none())
    member = forms.ModelChoiceField(queryset=Member.unscoped.none())
    product = forms.ModelChoiceField(queryset=LoanProduct.objects.none())
    requested_amount = forms.DecimalField(
        max_digits=18, decimal_places=2, min_value=Decimal("0.01")
    )
    term = forms.IntegerField(min_value=1)
    purpose = forms.CharField(max_length=500)
    idempotency_key = forms.UUIDField(initial=uuid.uuid4, widget=forms.HiddenInput())

    def __init__(self, *args, request, **kwargs):
        super().__init__(*args, **kwargs)
        allowed = request.user.accessible_branch_ids(request.active_branch_id)
        self.fields["branch"].queryset = Branch.unscoped.filter(
            pk__in=allowed, is_active=True
        ).order_by("name")
        self.fields["member"].queryset = Member.unscoped.filter(
            branch_id__in=allowed, status=Member.STATUS_ACTIVE
        ).order_by("member_code")
        self.fields["product"].queryset = LoanProduct.objects.filter(
            is_active=True
        ).order_by("code")


class LoanReviewForm(forms.Form):
    decision = forms.ChoiceField(
        choices=[
            (LoanApplication.STATUS_APPROVED, "Approve"),
            (LoanApplication.STATUS_REJECTED, "Reject"),
            (LoanApplication.STATUS_RETURNED, "Return"),
        ]
    )
    approved_amount = forms.DecimalField(
        max_digits=18, decimal_places=2, min_value=0, required=False
    )
    comment = forms.CharField(max_length=500)


class LoanDisbursementForm(forms.Form):
    disbursement_date = forms.DateField(initial=timezone.localdate)
    channel = forms.ChoiceField(choices=[("cash_in_hand", "Cash"), ("bank_accounts", "Bank")])
    idempotency_key = forms.UUIDField(initial=uuid.uuid4, widget=forms.HiddenInput())


class LoanRepaymentForm(forms.Form):
    amount = forms.DecimalField(max_digits=18, decimal_places=2, min_value=0)
    payment_date = forms.DateField(initial=timezone.localdate)
    payment_channel = forms.ChoiceField(choices=[("cash_in_hand", "Cash"), ("bank_accounts", "Bank")])
    idempotency_key = forms.UUIDField(initial=uuid.uuid4, widget=forms.HiddenInput())


class LoanRescheduleForm(forms.Form):
    new_term = forms.IntegerField(min_value=1)
    effective_date = forms.DateField(initial=timezone.localdate)
    reason = forms.CharField(max_length=500)
    idempotency_key = forms.UUIDField(initial=uuid.uuid4, widget=forms.HiddenInput())


class LoanWriteOffForm(forms.Form):
    write_off_date = forms.DateField(initial=timezone.localdate)
    reason = forms.CharField(max_length=500)
    idempotency_key = forms.UUIDField(initial=uuid.uuid4, widget=forms.HiddenInput())


class LoanRecoveryForm(forms.Form):
    amount = forms.DecimalField(max_digits=18, decimal_places=2, min_value=0)
    payment_date = forms.DateField(initial=timezone.localdate)
    payment_channel = forms.ChoiceField(choices=[("cash_in_hand", "Cash"), ("bank_accounts", "Bank")])
    idempotency_key = forms.UUIDField(initial=uuid.uuid4, widget=forms.HiddenInput())


class LoanSettlementForm(forms.Form):
    settlement_date = forms.DateField(initial=timezone.localdate)
    idempotency_key = forms.UUIDField(initial=uuid.uuid4, widget=forms.HiddenInput())

