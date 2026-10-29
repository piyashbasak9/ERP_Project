import uuid

from django import forms
from django.core.exceptions import ValidationError
from django.forms import BaseFormSet
from django.utils import timezone

from core.branch.models import Branch

from .models import (
    Account,
    AccountingPeriod,
    FiscalYear,
    SystemAccountMapping,
    VoucherSequence,
)


class AccountForm(forms.ModelForm):
    class Meta:
        model = Account
        fields = [
            'code', 'name', 'parent', 'account_type', 'normal_balance',
            'allows_direct_posting', 'is_system', 'is_active',
        ]
        widgets = {
            'code': forms.TextInput(attrs={'class': 'form-control'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'parent': forms.Select(attrs={'class': 'form-select'}),
            'account_type': forms.Select(attrs={'class': 'form-select'}),
            'normal_balance': forms.Select(attrs={'class': 'form-select'}),
            'allows_direct_posting': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_system': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['parent'].queryset = Account.objects.filter(is_active=True).exclude(pk=self.instance.pk)
        self.fields['parent'].required = False

    def clean(self):
        cleaned = super().clean()
        if self.instance.pk and self.instance.journal_lines.exists():
            immutable_fields = ('code', 'account_type', 'normal_balance')
            if any(cleaned.get(field) != getattr(self.instance, field) for field in immutable_fields):
                raise ValidationError(
                    'Account code, type and normal balance cannot change after ledger activity exists.'
                )
            if cleaned.get('allows_direct_posting') is False:
                raise ValidationError('An account with ledger activity must remain directly postable.')
        if self.instance.pk and self.instance.system_mappings.exists() and not cleaned.get('is_active'):
            raise ValidationError('An account mapped to a system transaction cannot be deactivated.')
        return cleaned


class FiscalYearForm(forms.ModelForm):
    class Meta:
        model = FiscalYear
        fields = ['name', 'start_date', 'end_date']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'start_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'end_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        }


class AccountingPeriodForm(forms.ModelForm):
    class Meta:
        model = AccountingPeriod
        fields = ['fiscal_year', 'number', 'name', 'start_date', 'end_date']
        widgets = {
            'fiscal_year': forms.Select(attrs={'class': 'form-select'}),
            'number': forms.NumberInput(attrs={'class': 'form-control', 'min': '1', 'max': '12'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'start_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'end_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['fiscal_year'].queryset = FiscalYear.objects.filter(is_closed=False)


class SystemAccountMappingForm(forms.ModelForm):
    class Meta:
        model = SystemAccountMapping
        fields = ['key', 'account']
        widgets = {
            'key': forms.Select(attrs={'class': 'form-select'}),
            'account': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['account'].queryset = Account.objects.filter(
            is_active=True,
            allows_direct_posting=True,
        ).order_by('code')


class JournalEntryForm(forms.Form):
    idempotency_key = forms.UUIDField(
        widget=forms.HiddenInput(),
        initial=uuid.uuid4,
    )
    branch = forms.ModelChoiceField(
        queryset=Branch.unscoped.none(),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    journal_date = forms.DateField(
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )
    voucher_type = forms.ChoiceField(
        choices=VoucherSequence.VOUCHER_TYPE_CHOICES,
        initial=VoucherSequence.VOUCHER_JOURNAL,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    narration = forms.CharField(
        max_length=500,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    requires_approval = forms.BooleanField(required=False)

    def __init__(self, *args, request, **kwargs):
        super().__init__(*args, **kwargs)
        branch_ids = request.user.accessible_branch_ids(request.active_branch_id)
        self.fields['branch'].queryset = Branch.unscoped.filter(
            pk__in=branch_ids,
            is_active=True,
        ).order_by('name')


class JournalLineForm(forms.Form):
    account = forms.ModelChoiceField(
        queryset=Account.objects.none(),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    debit = forms.DecimalField(
        max_digits=18,
        decimal_places=2,
        min_value=0,
        initial=0,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
    )
    credit = forms.DecimalField(
        max_digits=18,
        decimal_places=2,
        min_value=0,
        initial=0,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
    )
    narration = forms.CharField(
        required=False,
        max_length=255,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['account'].queryset = Account.objects.filter(
            is_active=True,
            allows_direct_posting=True,
        ).order_by('code')

    def clean(self):
        cleaned = super().clean()
        debit = cleaned.get('debit') or 0
        credit = cleaned.get('credit') or 0
        if self.has_changed() and (debit > 0) == (credit > 0):
            raise ValidationError('Enter an amount on exactly one side of the journal line.')
        return cleaned


class BalancedJournalLineFormSet(BaseFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        lines = [form.cleaned_data for form in self.forms if form.has_changed()]
        if len(lines) < 2:
            raise ValidationError('A journal entry must contain at least two lines.')
        debit_total = sum((line['debit'] for line in lines), start=0)
        credit_total = sum((line['credit'] for line in lines), start=0)
        if debit_total <= 0 or debit_total != credit_total:
            raise ValidationError('Total debits must equal total credits and be greater than zero.')


class ReversalForm(forms.Form):
    reversal_date = forms.DateField(
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )
    reason = forms.CharField(
        max_length=255,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )


class TrialBalanceForm(forms.Form):
    start_date = forms.DateField(
        initial=timezone.localdate,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )
    end_date = forms.DateField(
        initial=timezone.localdate,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )
    branch = forms.ModelChoiceField(
        queryset=Branch.unscoped.none(),
        required=False,
        empty_label='All accessible branches',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    def __init__(self, *args, request, **kwargs):
        super().__init__(*args, **kwargs)
        branch_ids = request.user.accessible_branch_ids(request.active_branch_id)
        self.fields['branch'].queryset = Branch.unscoped.filter(
            pk__in=branch_ids,
            is_active=True,
        ).order_by('name')
        if request.active_branch_id:
            self.fields['branch'].initial = request.active_branch_id

    def clean(self):
        cleaned = super().clean()
        start_date = cleaned.get('start_date')
        end_date = cleaned.get('end_date')
        if start_date and end_date and start_date > end_date:
            raise ValidationError('The start date must be on or before the end date.')
        return cleaned


class ReconciliationForm(forms.Form):
    branch = forms.ModelChoiceField(
        queryset=Branch.unscoped.none(),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    account = forms.ModelChoiceField(
        queryset=Account.objects.none(),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    as_of_date = forms.DateField(
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )
    statement_balance = forms.DecimalField(
        max_digits=18,
        decimal_places=2,
        min_value=0,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
    )
    notes = forms.CharField(
        required=False,
        max_length=500,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
    )

    def __init__(self, *args, request, **kwargs):
        super().__init__(*args, **kwargs)
        branch_ids = request.user.accessible_branch_ids(request.active_branch_id)
        self.fields['branch'].queryset = Branch.unscoped.filter(
            pk__in=branch_ids,
            is_active=True,
        ).order_by('name')
        self.fields['account'].queryset = Account.objects.filter(
            account_type=Account.ASSET,
            is_active=True,
            allows_direct_posting=True,
        ).order_by('code')
