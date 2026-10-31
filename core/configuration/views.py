import mimetypes

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import FileResponse, Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from core.accounts.models import Permission
from core.common.popup import popup_json_response, render_popup_form
from core.loans.models import LoanApprovalTier, LoanPARBucket, LoanProduct
from core.savings.models import SavingsProduct

from .forms import (
    BusinessRulesForm,
    OrganizationConfigurationForm,
    SystemConfigurationForm,
    UserPreferenceForm,
)
from .models import (
    BusinessRules,
    OrganizationConfiguration,
    SystemConfiguration,
    UserPreference,
)
from .services import (
    get_business_rules,
    get_organization_configuration,
    get_system_configuration,
    save_configuration,
)

CONFIGURATION_SCREENS = {
    "system": (
        SystemConfiguration,
        SystemConfigurationForm,
        (
            "application_name", "logo", "currency_code", "currency_symbol",
            "number_format", "date_format", "time_zone",
            "fiscal_year_start_month", "fiscal_year_start_day",
            "minimum_password_length", "session_idle_minutes", "upload_limit_mb",
        ),
    ),
    "organization": (
        OrganizationConfiguration,
        OrganizationConfigurationForm,
        (
            "legal_name", "registration_number", "address", "phone", "email",
            "website", "logo",
        ),
    ),
}


@require_GET
def index(request):
    allowed = (
        None
        if request.user.is_superuser
        else set(
            Permission.objects.filter(
                role_permissions__role__user_roles__user=request.user,
                is_allowed=True,
                is_active=True,
            ).values_list("route_name", flat=True)
        )
    )
    screens = [
        ("System configuration", "Module_Settings_system"),
        ("Organization settings", "Module_Settings_organization"),
        ("User preferences", "Module_Settings_preferences"),
        ("Business rules", "Module_Settings_business_rules"),
        ("Notification templates", "Module_Settings_notification_templates"),
    ]
    return render(
        request,
        "configuration/index.html",
        {
            "screens": [
                {"title": title, "url": reverse(f"configuration:{route_name}")}
                for title, route_name in screens
                if allowed is None or route_name in allowed
            ]
        },
    )


def _configuration_form(request, screen):
    model, form_class, fields = CONFIGURATION_SCREENS[screen]
    instance = (
        SystemConfiguration.objects.order_by("pk").first()
        or SystemConfiguration()
        if model is SystemConfiguration
        else OrganizationConfiguration.objects.order_by("pk").first()
        or OrganizationConfiguration()
    )
    form = form_class(request.POST or None, request.FILES or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        record = form.save(commit=False)
        try:
            save_configuration(
                instance=record,
                fields=fields,
                user=request.user,
                entity_name=model.__name__,
            )
        except ValidationError as error:
            form.add_error(None, error)
        else:
            message = f"{screen.replace('-', ' ').title()} saved."
            response = popup_json_response(
                request, message=message, data={"id": record.pk}
            )
            if response is not None:
                return response
            messages.success(request, message)
            return redirect(f"configuration:Module_Settings_{screen}")
    return render_popup_form(
        request,
        "configuration/form.html",
        {
            "form": form,
            "title": screen.replace("-", " ").title(),
            "save_url": reverse(f"configuration:Module_Settings_{screen}_save"),
            "cancel_url": reverse("configuration:Module_Settings_index"),
        },
        status=400 if request.method == "POST" else 200,
    )


@require_GET
def system_configuration(request):
    return _configuration_form(request, "system")


@require_GET
def organization_configuration(request):
    return _configuration_form(request, "organization")


@require_POST
def save_system_configuration(request):
    return _configuration_form(request, "system")


@require_POST
def save_organization_configuration(request):
    return _configuration_form(request, "organization")


@require_GET
def organization_logo(request):
    logo = get_organization_configuration().logo
    if not logo:
        raise Http404("No organization logo is configured.")
    content_type = mimetypes.guess_type(logo.name)[0] or "application/octet-stream"
    return FileResponse(logo.open("rb"), content_type=content_type)


@require_GET
def system_logo(request):
    logo = get_system_configuration().logo
    if not logo:
        raise Http404("No application logo is configured.")
    content_type = mimetypes.guess_type(logo.name)[0] or "application/octet-stream"
    return FileResponse(logo.open("rb"), content_type=content_type)


@require_GET
def user_preferences(request):
    instance = UserPreference.objects.filter(user=request.user).first()
    form = UserPreferenceForm(instance=instance)
    return render_popup_form(
        request,
        "configuration/form.html",
        {
            "form": form,
            "title": "User preferences",
            "save_url": reverse("configuration:Module_Settings_preferences_save"),
            "cancel_url": reverse("configuration:Module_Settings_index"),
        },
    )


@require_POST
def save_user_preferences(request):
    instance = UserPreference.objects.filter(user=request.user).first()
    old_values = (
        {
            field: getattr(instance, field)
            for field in UserPreferenceForm.Meta.fields
        }
        if instance
        else None
    )
    form = UserPreferenceForm(request.POST, instance=instance)
    if form.is_valid():
        preference = form.save(commit=False)
        preference.user = request.user
        preference.full_clean()
        preference.save()
        from core.audit.services import log_action

        log_action(
            "Update" if instance else "Create",
            "UserPreference",
            preference.pk,
            old_values=old_values,
            new_values={
                field: getattr(preference, field)
                for field in UserPreferenceForm.Meta.fields
            },
        )
        response = popup_json_response(
            request,
            message="Your preferences were saved.",
            data={"id": preference.pk},
        )
        if response is not None:
            return response
        messages.success(request, "Your preferences were saved.")
        return redirect("configuration:Module_Settings_preferences")
    return render_popup_form(
        request,
        "configuration/form.html",
        {
            "form": form,
            "title": "User preferences",
            "save_url": reverse("configuration:Module_Settings_preferences_save"),
            "cancel_url": reverse("configuration:Module_Settings_index"),
        },
        status=400,
    )


@require_GET
def business_rules(request):
    instance = get_business_rules()
    form = BusinessRulesForm(instance=instance)
    return render_popup_form(
        request,
        "configuration/business_rules.html",
        {
            "form": form,
            "title": "Business rules",
            "save_url": reverse("configuration:Module_Settings_business_rules_save"),
            "cancel_url": reverse("configuration:Module_Settings_index"),
            "loan_products": LoanProduct.objects.order_by("code"),
            "savings_products": SavingsProduct.objects.order_by("code"),
            "approval_tiers": LoanApprovalTier.objects.select_related("role", "branch"),
            "par_buckets": LoanPARBucket.objects.order_by("minimum_days"),
            "loan_product_url": reverse("loans:Module_Loans_products"),
            "savings_product_url": reverse("savings:Module_Savings_products"),
            "approval_tier_url": reverse("loans:Module_Loans_approval_tiers"),
            "par_bucket_url": reverse("loans:Module_Loans_par_buckets"),
        },
    )


@require_POST
def save_business_rules(request):
    instance = get_business_rules()
    form = BusinessRulesForm(request.POST, instance=instance)
    if form.is_valid():
        rules = form.save(commit=False)
        try:
            save_configuration(
                instance=rules,
                fields=(
                    "repayment_allocation_order", "member_status_rules",
                    "collection_rules", "rounding_mode",
                ),
                user=request.user,
                entity_name=BusinessRules.__name__,
            )
        except ValidationError as error:
            form.add_error(None, error)
        else:
            response = popup_json_response(
                request, message="Business rules saved.", data={"id": rules.pk}
            )
            if response is not None:
                return response
            messages.success(request, "Business rules saved.")
            return redirect("configuration:Module_Settings_business_rules")
    return render_popup_form(
        request,
        "configuration/business_rules.html",
        {
            "form": form,
            "title": "Business rules",
            "save_url": reverse("configuration:Module_Settings_business_rules_save"),
            "cancel_url": reverse("configuration:Module_Settings_index"),
            "loan_products": LoanProduct.objects.order_by("code"),
            "savings_products": SavingsProduct.objects.order_by("code"),
            "approval_tiers": LoanApprovalTier.objects.select_related("role", "branch"),
            "par_buckets": LoanPARBucket.objects.order_by("minimum_days"),
            "loan_product_url": reverse("loans:Module_Loans_products"),
            "savings_product_url": reverse("savings:Module_Savings_products"),
            "approval_tier_url": reverse("loans:Module_Loans_approval_tiers"),
            "par_bucket_url": reverse("loans:Module_Loans_par_buckets"),
        },
        status=400,
    )
