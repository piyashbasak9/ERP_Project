import uuid
from decimal import Decimal

from django import forms
from django.db.models import Q
from django.utils import timezone

from core.branch.models import Branch, Member

from .models import LoanApplication, LoanApprovalTier, LoanPARBucket, LoanProduct


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
            "penalty_type",
            "penalty_frequency",
            "penalty_cap_rate",
            "required_savings_rate",
            "max_concurrent_loans",
            "cycle_limits",
            "approval_limit",
            "early_settlement_fee",
            "early_settlement_policy",
            "overpayment_policy",
            "holiday_convention",
            "requires_verified_kyc",
            "requires_guarantor",
            "requires_collateral",
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
    guarantor = forms.ModelChoiceField(
        queryset=Member.unscoped.none(), required=False
    )
    collateral_description = forms.CharField(max_length=255, required=False)
    collateral_reference = forms.CharField(max_length=80, required=False)
    collateral_value = forms.DecimalField(
        max_digits=18, decimal_places=2, min_value=Decimal("0.01"), required=False
    )
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
        self.fields["guarantor"].queryset = Member.unscoped.filter(
            branch_id__in=allowed, status=Member.STATUS_ACTIVE
        ).order_by("member_code")
        self.fields["product"].queryset = LoanProduct.objects.filter(
            is_active=True
        ).order_by("code")

    def clean(self):
        cleaned = super().clean()
        product = cleaned.get("product")
        member = cleaned.get("member")
        guarantor = cleaned.get("guarantor")
        description = cleaned.get("collateral_description", "").strip()
        collateral_value = cleaned.get("collateral_value")
        reference = cleaned.get("collateral_reference", "").strip()
        if product and product.requires_guarantor and not guarantor:
            self.add_error("guarantor", "This product requires a guarantor.")
        if product and product.requires_collateral and (
            not description or collateral_value is None
        ):
            self.add_error(
                "collateral_description",
                "This product requires a collateral description and value.",
            )
        if guarantor and member and guarantor.pk == member.pk:
            self.add_error("guarantor", "The applicant cannot guarantee their own loan.")
        if any((description, reference, collateral_value is not None)) and (
            not description or collateral_value is None
        ):
            self.add_error(
                "collateral_description",
                "Provide both a collateral description and value.",
            )
        return cleaned


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
    reason = forms.CharField(max_length=500)
    idempotency_key = forms.UUIDField(initial=uuid.uuid4, widget=forms.HiddenInput())


class LoanApprovalTierForm(forms.ModelForm):
    class Meta:
        model = LoanApprovalTier
        fields = ["branch_type", "branch", "role", "amount_limit", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")


class LoanPARBucketForm(forms.ModelForm):
    class Meta:
        model = LoanPARBucket
        fields = ["name", "minimum_days", "maximum_days", "provision_rate", "is_active"]

    def clean(self):
        cleaned = super().clean()
        minimum = cleaned.get("minimum_days")
        maximum = cleaned.get("maximum_days")
        if minimum is not None and maximum is not None and maximum < minimum:
            self.add_error("maximum_days", "Maximum days must not be less than minimum days.")
            return cleaned
        if minimum is not None:
            overlaps = LoanPARBucket.objects.filter(
                minimum_days__lte=maximum if maximum is not None else 32767,
            ).filter(
                Q(maximum_days__isnull=True) | Q(maximum_days__gte=minimum)
            )
            if self.instance.pk:
                overlaps = overlaps.exclude(pk=self.instance.pk)
            if overlaps.exists():
                self.add_error("minimum_days", "Classification day ranges cannot overlap.")
        return cleaned
