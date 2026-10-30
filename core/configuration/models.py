from datetime import date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


def private_logo_path(instance, filename):
    return f"organization/logos/{filename}"


def default_repayment_allocation_order():
    return ["penalty", "fees", "interest", "principal"]


def default_member_status_rules():
    return {
        "loan_application": ["active"],
        "savings_deposit": ["active", "inactive"],
        "savings_withdrawal": ["active"],
        "loan_repayment": ["active", "inactive", "suspended"],
    }


def default_collection_rules():
    return {
        "require_short_collection_reason": True,
        "allow_advance_collection": True,
    }


class SystemConfiguration(models.Model):
    NUMBER_FORMAT_CHOICES = [
        ("western", "1,234,567.89"),
        ("indian", "12,34,567.89"),
    ]
    DATE_FORMAT_CHOICES = [
        ("%d-%b-%Y", "30-Oct-2026"),
        ("%Y-%m-%d", "2026-10-30"),
        ("%d/%m/%Y", "30/10/2026"),
    ]

    application_name = models.CharField(max_length=100, default="ERP Management")
    logo = models.ImageField(upload_to=private_logo_path, blank=True)
    currency_code = models.CharField(max_length=3, default="BDT")
    currency_symbol = models.CharField(max_length=8, default="৳")
    number_format = models.CharField(
        max_length=12, choices=NUMBER_FORMAT_CHOICES, default="western"
    )
    date_format = models.CharField(
        max_length=12, choices=DATE_FORMAT_CHOICES, default="%d-%b-%Y"
    )
    time_zone = models.CharField(max_length=64, default="UTC")
    fiscal_year_start_month = models.PositiveSmallIntegerField(default=1)
    fiscal_year_start_day = models.PositiveSmallIntegerField(default=1)
    minimum_password_length = models.PositiveSmallIntegerField(default=12)
    session_idle_minutes = models.PositiveSmallIntegerField(default=30)
    upload_limit_mb = models.PositiveSmallIntegerField(default=2)

    class Meta:
        db_table = "system_configuration"

    def clean(self):
        errors = {}
        if len(self.currency_code) != 3 or not self.currency_code.isalpha():
            errors["currency_code"] = "Enter a three-letter currency code."
        try:
            ZoneInfo(self.time_zone)
        except (ZoneInfoNotFoundError, TypeError):
            errors["time_zone"] = "Select a valid IANA time zone."
        try:
            date(2000, self.fiscal_year_start_month, self.fiscal_year_start_day)
        except (TypeError, ValueError):
            errors["fiscal_year_start_day"] = "Enter a valid fiscal year start date."
        if not 8 <= self.minimum_password_length <= 128:
            errors["minimum_password_length"] = "Password length must be between 8 and 128."
        if not 5 <= self.session_idle_minutes <= 1440:
            errors["session_idle_minutes"] = "Session idle timeout must be 5 to 1440 minutes."
        if not 1 <= self.upload_limit_mb <= 50:
            errors["upload_limit_mb"] = "Upload limit must be between 1 and 50 MB."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.application_name


class OrganizationConfiguration(models.Model):
    legal_name = models.CharField(max_length=200, default="Organization")
    registration_number = models.CharField(max_length=100, blank=True, default="")
    address = models.CharField(max_length=500, blank=True, default="")
    phone = models.CharField(max_length=40, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    website = models.URLField(blank=True, default="")
    logo = models.ImageField(upload_to=private_logo_path, blank=True)

    class Meta:
        db_table = "organization_configuration"

    def __str__(self):
        return self.legal_name


class UserPreference(models.Model):
    LANGUAGE_CHOICES = [
        ("en-us", "English"),
        ("bn", "Bangla"),
    ]
    PAGE_SIZE_CHOICES = [(25, "25"), (50, "50"), (100, "100")]
    LANDING_PAGE_CHOICES = [
        ("/", "Dashboard"),
        ("/reports/", "Reports"),
        ("/loans/portfolio/", "Loan portfolio"),
        ("/savings/accounts/", "Savings accounts"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="preferences",
    )
    language = models.CharField(max_length=10, choices=LANGUAGE_CHOICES, default="en-us")
    default_page_size = models.PositiveSmallIntegerField(
        choices=PAGE_SIZE_CHOICES, default=25
    )
    default_landing_page = models.CharField(
        max_length=100, choices=LANDING_PAGE_CHOICES, default="/"
    )
    date_format = models.CharField(
        max_length=12,
        choices=SystemConfiguration.DATE_FORMAT_CHOICES,
        default="%d-%b-%Y",
    )

    class Meta:
        db_table = "user_preferences"


class BusinessRules(models.Model):
    ROUNDING_CHOICES = [
        ("ROUND_HALF_UP", "Half up"),
        ("ROUND_HALF_EVEN", "Half even"),
        ("ROUND_DOWN", "Down"),
    ]

    repayment_allocation_order = models.JSONField(
        default=default_repayment_allocation_order
    )
    member_status_rules = models.JSONField(
        default=default_member_status_rules
    )
    collection_rules = models.JSONField(default=default_collection_rules)
    rounding_mode = models.CharField(
        max_length=20, choices=ROUNDING_CHOICES, default="ROUND_HALF_UP"
    )

    class Meta:
        db_table = "business_rules"

    def clean(self):
        required_components = {"penalty", "fees", "interest", "principal"}
        if (
            not isinstance(self.repayment_allocation_order, list)
            or set(self.repayment_allocation_order) != required_components
            or len(self.repayment_allocation_order) != len(required_components)
        ):
            raise ValidationError(
                {
                    "repayment_allocation_order":
                        "Choose each repayment component exactly once."
                }
            )
        if not isinstance(self.member_status_rules, dict):
            raise ValidationError({"member_status_rules": "Enter a valid status-rule object."})
        if not isinstance(self.collection_rules, dict):
            raise ValidationError({"collection_rules": "Enter a valid collection-rule object."})

    def __str__(self):
        return "Shared business rules"
