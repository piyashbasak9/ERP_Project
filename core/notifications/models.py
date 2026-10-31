from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from .template_validation import EVENT_PLACEHOLDERS, validate_template


class NotificationPreference(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_preference",
    )
    email_enabled = models.BooleanField(default=True)
    in_app_enabled = models.BooleanField(default=True)
    sms_enabled = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)


class NotificationConfiguration(models.Model):
    installment_days_before = models.PositiveSmallIntegerField(default=3)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        if not 0 <= self.installment_days_before <= 90:
            raise ValidationError(
                {"installment_days_before": "Reminder days must be from 0 through 90."}
            )

    @classmethod
    def current(cls):
        return cls.objects.order_by("pk").first() or cls()


class NotificationTemplate(models.Model):
    EVENT_CHOICES = [(key, key.replace("_", " ").title()) for key in EVENT_PLACEHOLDERS]

    event_key = models.CharField(max_length=32, choices=EVENT_CHOICES, unique=True)
    subject = models.CharField(max_length=180)
    body = models.TextField(max_length=2000)
    enabled = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        validate_template(self.event_key, self.subject, self.body)


class Notification(models.Model):
    CHANNEL_EMAIL = "email"
    CHANNEL_IN_APP = "in_app"
    CHANNEL_SMS = "sms"
    CHANNEL_CHOICES = [
        (CHANNEL_EMAIL, "Email"),
        (CHANNEL_IN_APP, "In-app"),
        (CHANNEL_SMS, "SMS"),
    ]
    STATUS_PENDING = "pending"
    STATUS_SENT = "sent"
    STATUS_FAILED = "failed"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_SENT, "Sent"),
        (STATUS_FAILED, "Failed"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    branch = models.ForeignKey("branch.Branch", on_delete=models.PROTECT)
    event_key = models.CharField(max_length=32, choices=NotificationTemplate.EVENT_CHOICES)
    event_reference = models.CharField(max_length=100)
    event_date = models.DateField()
    channel = models.CharField(max_length=12, choices=CHANNEL_CHOICES)
    subject = models.CharField(max_length=180)
    body = models.TextField(max_length=2000)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_PENDING)
    is_read = models.BooleanField(default=False)
    attempts = models.PositiveSmallIntegerField(default=0)
    retry_at = models.DateTimeField(null=True, blank=True, db_index=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    failure_code = models.CharField(max_length=40, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "notifications"
        constraints = [
            models.UniqueConstraint(
                fields=(
                    "recipient",
                    "event_key",
                    "event_reference",
                    "event_date",
                    "channel",
                ),
                name="uniq_notification_recipient_event_day_channel",
            )
        ]
        indexes = [
            models.Index(fields=("recipient", "is_read", "created_at")),
            models.Index(fields=("status", "retry_at")),
        ]
