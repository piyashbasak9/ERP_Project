import uuid

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from core.branch.models import Branch, Group, Member

from .models import SavingsAccount, SavingsProduct, SavingsTransaction


class SavingsProductForm(forms.ModelForm):
    class Meta:
        model = SavingsProduct
        fields = [
            'code',
            'name',
            'savings_type',
            'annual_interest_rate',
            'interest_method',
            'posting_frequency',
            'minimum_opening_balance',
            'minimum_balance',
            'dormant_after_days',
            'pays_interest_when_dormant',
            'fee_amount',
            'maximum_withdrawal',
            'withdrawal_approval_threshold',
            'withholding_tax_rate',
            'allow_withdrawals',
            'is_active',
        ]
        widgets = {
            'code': forms.TextInput(attrs={'class': 'form-control'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'savings_type': forms.Select(attrs={'class': 'form-select'}),
            'annual_interest_rate': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.000001'}),
            'interest_method': forms.Select(attrs={'class': 'form-select'}),
            'posting_frequency': forms.Select(attrs={'class': 'form-select'}),
            'minimum_opening_balance': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'minimum_balance': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'dormant_after_days': forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
            'pays_interest_when_dormant': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'fee_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'maximum_withdrawal': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'withdrawal_approval_threshold': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'withholding_tax_rate': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.000001'}),
            'allow_withdrawals': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class SavingsAccountForm(forms.Form):
    OWNER_MEMBER = 'member'
    OWNER_GROUP = 'group'
    OWNER_CHOICES = [(OWNER_MEMBER, 'Individual member'), (OWNER_GROUP, 'Group')]

    branch = forms.ModelChoiceField(
        queryset=Branch.unscoped.none(),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    product = forms.ModelChoiceField(
        queryset=SavingsProduct.objects.none(),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    owner_type = forms.ChoiceField(
        choices=OWNER_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    member = forms.ModelChoiceField(
        queryset=Member.objects.none(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    group = forms.ModelChoiceField(
        queryset=Group.objects.none(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    contribution_member = forms.ModelChoiceField(
        queryset=Member.objects.none(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    opened_at = forms.DateField(
        initial=timezone.localdate,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )
    opening_balance = forms.DecimalField(
        max_digits=18,
        decimal_places=2,
        min_value=0,
        initial=0,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
    )
    idempotency_key = forms.UUIDField(
        initial=uuid.uuid4,
        widget=forms.HiddenInput(),
    )

    def __init__(self, *args, request, **kwargs):
        super().__init__(*args, **kwargs)
        allowed = request.user.accessible_branch_ids(request.active_branch_id)
        self.fields['branch'].queryset = Branch.unscoped.filter(
            pk__in=allowed,
            is_active=True,
        ).order_by('name')
        self.fields['product'].queryset = SavingsProduct.objects.filter(is_active=True).order_by('code')
        self.fields['member'].queryset = Member.unscoped.filter(
            branch_id__in=allowed,
            status=Member.STATUS_ACTIVE,
        ).order_by('member_code')
        self.fields['group'].queryset = Group.unscoped.filter(
            branch_id__in=allowed,
            is_active=True,
        ).order_by('code')
        self.fields['contribution_member'].queryset = Member.unscoped.filter(
            branch_id__in=allowed,
            status__in=[Member.STATUS_ACTIVE, Member.STATUS_INACTIVE],
        ).order_by('member_code')

    def clean(self):
        cleaned = super().clean()
        branch = cleaned.get('branch')
        owner_type = cleaned.get('owner_type')
        member = cleaned.get('member')
        group = cleaned.get('group')
        contribution_member = cleaned.get('contribution_member')
        opening_balance = cleaned.get('opening_balance')

        if owner_type == self.OWNER_MEMBER:
            if member is None:
                self.add_error('member', 'Select the account owner.')
            if group:
                self.add_error('group', 'An individual account cannot also belong to a group.')
            if member and branch and member.branch_id != branch.pk:
                self.add_error('member', 'The member must belong to the selected branch.')
        elif owner_type == self.OWNER_GROUP:
            if group is None:
                self.add_error('group', 'Select the account group.')
            if member:
                self.add_error('member', 'A group account cannot also belong to an individual member.')
            if group and branch and group.branch_id != branch.pk:
                self.add_error('group', 'The group must belong to the selected branch.')
            if opening_balance and opening_balance > 0 and contribution_member is None:
                self.add_error('contribution_member', 'Select the member making the opening contribution.')
            if contribution_member and group and contribution_member.group_id != group.pk:
                self.add_error('contribution_member', 'The contributor must belong to the selected group.')
        return cleaned


class SavingsTransactionForm(forms.Form):
    account = forms.ModelChoiceField(
        queryset=SavingsAccount.objects.none(),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    amount = forms.DecimalField(
        max_digits=18,
        decimal_places=2,
        min_value=0.01,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
    )
    transaction_date = forms.DateField(
        initial=timezone.localdate,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )
    payment_channel = forms.ChoiceField(
        choices=SavingsTransaction.CHANNEL_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    contribution_member = forms.ModelChoiceField(
        queryset=Member.objects.none(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    idempotency_key = forms.UUIDField(
        initial=uuid.uuid4,
        widget=forms.HiddenInput(),
    )
    narration = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )

    def __init__(self, *args, request, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['account'].queryset = SavingsAccount.objects.filter(
            status=SavingsAccount.STATUS_ACTIVE,
        ).select_related('product', 'member', 'group').order_by('account_number')
        allowed = request.user.accessible_branch_ids(request.active_branch_id)
        self.fields['contribution_member'].queryset = Member.unscoped.filter(
            branch_id__in=allowed,
            status__in=[Member.STATUS_ACTIVE, Member.STATUS_INACTIVE],
        ).order_by('member_code')

    def clean(self):
        cleaned = super().clean()
        account = cleaned.get('account')
        contributor = cleaned.get('contribution_member')
        if account and account.group_id:
            if contributor is None:
                self.add_error('contribution_member', 'Select the contributing group member.')
            elif contributor.group_id != account.group_id:
                self.add_error('contribution_member', 'The contributor must belong to this account group.')
        elif contributor:
            self.add_error('contribution_member', 'Individual savings accounts do not use group contributors.')
        return cleaned


class SavingsInterestForm(forms.Form):
    account = forms.ModelChoiceField(
        queryset=SavingsAccount.objects.none(),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    start_date = forms.DateField(widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}))
    end_date = forms.DateField(widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}))
    idempotency_key = forms.UUIDField(initial=uuid.uuid4, widget=forms.HiddenInput())

    def __init__(self, *args, request, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['account'].queryset = SavingsAccount.objects.filter(
            status=SavingsAccount.STATUS_ACTIVE,
        ).select_related('product').order_by('account_number')

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get('start_date')
        end = cleaned.get('end_date')
        if start and end and end < start:
            raise ValidationError('The interest period end date must not precede its start date.')
        return cleaned


class SavingsFeeForm(forms.Form):
    account = forms.ModelChoiceField(
        queryset=SavingsAccount.objects.none(),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    transaction_date = forms.DateField(
        initial=timezone.localdate,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )
    idempotency_key = forms.UUIDField(initial=uuid.uuid4, widget=forms.HiddenInput())
    narration = forms.CharField(
        max_length=255,
        required=False,
        initial='Product fee',
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )

    def __init__(self, *args, request, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['account'].queryset = SavingsAccount.objects.filter(
            status=SavingsAccount.STATUS_ACTIVE,
        ).select_related('product').order_by('account_number')


class SavingsReversalForm(forms.Form):
    reversal_date = forms.DateField(
        initial=timezone.localdate,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )
    reason = forms.CharField(
        max_length=255,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )


class WithdrawalRejectionForm(forms.Form):
    reason = forms.CharField(
        max_length=255,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )


class SavingsReactivationForm(forms.Form):
    reason = forms.CharField(
        max_length=255,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )


class SavingsReactivationReasonForm(forms.Form):
    reason = forms.CharField(
        max_length=255,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
