import json
from zoneinfo import available_timezones

from django import forms
from django.core.exceptions import ValidationError

from .models import (
    BusinessRules,
    OrganizationConfiguration,
    SystemConfiguration,
    UserPreference,
)


class StyledModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", "form-check-input")
            elif isinstance(field.widget, forms.ClearableFileInput):
                field.widget.attrs.setdefault("class", "form-control")
            else:
                field.widget.attrs.setdefault("class", "form-control")


class SystemConfigurationForm(StyledModelForm):
    class Meta:
        model = SystemConfiguration
        fields = [
            "application_name", "logo", "currency_code", "currency_symbol",
            "number_format", "date_format", "time_zone",
            "fiscal_year_start_month", "fiscal_year_start_day",
            "minimum_password_length", "session_idle_minutes", "upload_limit_mb",
        ]
        widgets = {
            "time_zone": forms.Select(
                choices=[(zone, zone) for zone in sorted(available_timezones())]
            ),
            "fiscal_year_start_month": forms.NumberInput(attrs={"min": 1, "max": 12}),
            "fiscal_year_start_day": forms.NumberInput(attrs={"min": 1, "max": 31}),
            "minimum_password_length": forms.NumberInput(attrs={"min": 8, "max": 128}),
            "session_idle_minutes": forms.NumberInput(attrs={"min": 5, "max": 1440}),
            "upload_limit_mb": forms.NumberInput(attrs={"min": 1, "max": 50}),
        }


class OrganizationConfigurationForm(StyledModelForm):
    class Meta:
        model = OrganizationConfiguration
        fields = [
            "legal_name", "registration_number", "address", "phone", "email",
            "website", "logo",
        ]


class UserPreferenceForm(StyledModelForm):
    class Meta:
        model = UserPreference
        fields = [
            "language", "default_page_size", "default_landing_page", "date_format"
        ]


class BusinessRulesForm(StyledModelForm):
    repayment_allocation_order = forms.MultipleChoiceField(
        choices=[
            ("penalty", "Penalty"),
            ("fees", "Fees"),
            ("interest", "Interest"),
            ("principal", "Principal"),
        ],
        widget=forms.SelectMultiple(attrs={"size": 4}),
        help_text="Select every component once. The stored order controls repayment allocation.",
    )
    member_status_rules_json = forms.CharField(
        label="Member status rules (JSON)",
        widget=forms.Textarea(attrs={"rows": 6, "class": "form-control"}),
    )
    collection_rules_json = forms.CharField(
        label="Collection rules (JSON)",
        widget=forms.Textarea(attrs={"rows": 4, "class": "form-control"}),
    )

    class Meta:
        model = BusinessRules
        fields = ["rounding_mode"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["repayment_allocation_order"].initial = (
            self.instance.repayment_allocation_order
        )
        self.fields["member_status_rules_json"].initial = json.dumps(
            self.instance.member_status_rules, indent=2, sort_keys=True
        )
        self.fields["collection_rules_json"].initial = json.dumps(
            self.instance.collection_rules, indent=2, sort_keys=True
        )

    def clean_member_status_rules_json(self):
        try:
            value = json.loads(self.cleaned_data["member_status_rules_json"])
        except json.JSONDecodeError as error:
            raise ValidationError("Enter valid JSON.") from error
        allowed_statuses = {"active", "inactive", "suspended"}
        if (
            not isinstance(value, dict)
            or not value
            or any(
                not isinstance(statuses, list)
                or not statuses
                or set(statuses) - allowed_statuses
                for statuses in value.values()
            )
        ):
            raise ValidationError("Use action names mapped to valid member-status lists.")
        return value

    def clean_collection_rules_json(self):
        try:
            value = json.loads(self.cleaned_data["collection_rules_json"])
        except json.JSONDecodeError as error:
            raise ValidationError("Enter valid JSON.") from error
        if (
            not isinstance(value, dict)
            or set(value) != {
                "require_short_collection_reason", "allow_advance_collection"
            }
            or any(not isinstance(item, bool) for item in value.values())
        ):
            raise ValidationError(
                "Set require_short_collection_reason and allow_advance_collection to true or false."
            )
        return value

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.repayment_allocation_order = self.cleaned_data[
            "repayment_allocation_order"
        ]
        instance.member_status_rules = self.cleaned_data["member_status_rules_json"]
        instance.collection_rules = self.cleaned_data["collection_rules_json"]
        if commit:
            instance.save()
        return instance
