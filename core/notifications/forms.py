from django import forms
from django.core.exceptions import ValidationError

from .models import (
    NotificationConfiguration,
    NotificationPreference,
    NotificationTemplate,
)


class NotificationPreferenceForm(forms.ModelForm):
    class Meta:
        model = NotificationPreference
        fields = ("email_enabled", "in_app_enabled", "sms_enabled")


class NotificationTemplateForm(forms.ModelForm):
    class Meta:
        model = NotificationTemplate
        fields = ("event_key", "subject", "body", "enabled")

    def clean(self):
        cleaned_data = super().clean()
        template = NotificationTemplate(
            event_key=cleaned_data.get("event_key", ""),
            subject=cleaned_data.get("subject", ""),
            body=cleaned_data.get("body", ""),
            enabled=cleaned_data.get("enabled", True),
        )
        try:
            template.clean()
        except ValidationError as exc:
            self.add_error(None, exc)
        return cleaned_data


class NotificationConfigurationForm(forms.ModelForm):
    class Meta:
        model = NotificationConfiguration
        fields = ("installment_days_before",)
