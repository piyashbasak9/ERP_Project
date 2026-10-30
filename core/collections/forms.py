import uuid

from django import forms

from core.branch.models import Center, Group, Staff


class CollectionSheetForm(forms.Form):
    center = forms.ModelChoiceField(
        queryset=Center.unscoped.none(),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    group = forms.ModelChoiceField(
        queryset=Group.unscoped.none(),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    field_officer = forms.ModelChoiceField(
        queryset=Staff.unscoped.none(),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    collection_date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"})
    )
    idempotency_key = forms.UUIDField(
        initial=uuid.uuid4, widget=forms.HiddenInput()
    )

    def __init__(self, *args, request, **kwargs):
        super().__init__(*args, **kwargs)
        allowed = request.user.accessible_branch_ids(request.active_branch_id)
        self.fields["center"].queryset = Center.unscoped.filter(
            branch_id__in=allowed, is_active=True
        ).select_related("branch")
        self.fields["group"].queryset = Group.unscoped.filter(
            branch_id__in=allowed, is_active=True
        ).select_related("center")
        self.fields["field_officer"].queryset = Staff.unscoped.filter(
            branch_id__in=allowed, is_active=True, user__isnull=False
        )

    def clean(self):
        cleaned = super().clean()
        center = cleaned.get("center")
        group = cleaned.get("group")
        officer = cleaned.get("field_officer")
        if center and group and group.center_id != center.pk:
            self.add_error("group", "Select a group in the selected center.")
        if center and officer and officer.branch_id != center.branch_id:
            self.add_error("field_officer", "Select an officer from the center's branch.")
        return cleaned


class CollectionEntryForm(forms.Form):
    collected_amount = forms.DecimalField(
        min_value=0,
        max_digits=18,
        decimal_places=2,
        widget=forms.NumberInput(
            attrs={"class": "form-control", "min": "0", "step": "0.01"}
        ),
    )
    savings_amount = forms.DecimalField(
        min_value=0,
        max_digits=18,
        decimal_places=2,
        widget=forms.NumberInput(
            attrs={"class": "form-control", "min": "0", "step": "0.01"}
        ),
    )
    reason = forms.CharField(
        required=False,
        max_length=255,
        widget=forms.TextInput(
            attrs={"class": "form-control", "maxlength": "255"}
        ),
    )


class ReconciliationForm(forms.Form):
    cash_received = forms.DecimalField(
        min_value=0,
        max_digits=18,
        decimal_places=2,
        widget=forms.NumberInput(
            attrs={"class": "form-control", "min": "0", "step": "0.01"}
        ),
    )


class CancellationForm(forms.Form):
    reason = forms.CharField(
        max_length=255,
        widget=forms.TextInput(
            attrs={"class": "form-control", "maxlength": "255"}
        ),
    )


class ReversalRequestForm(forms.Form):
    reversal_date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"})
    )
    reason = forms.CharField(
        max_length=500,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}),
    )
    idempotency_key = forms.UUIDField(
        initial=uuid.uuid4, widget=forms.HiddenInput()
    )
