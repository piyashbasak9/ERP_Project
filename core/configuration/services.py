from decimal import ROUND_DOWN, ROUND_HALF_EVEN, ROUND_HALF_UP

from django.core.cache import cache

from core.audit.services import log_action

from .models import BusinessRules, OrganizationConfiguration, SystemConfiguration

SYSTEM_CACHE_KEY = "erp:configuration:system"
ORGANIZATION_CACHE_KEY = "erp:configuration:organization"
BUSINESS_RULES_CACHE_KEY = "erp:configuration:business-rules"
ROUNDING_MODES = {
    "ROUND_HALF_UP": ROUND_HALF_UP,
    "ROUND_HALF_EVEN": ROUND_HALF_EVEN,
    "ROUND_DOWN": ROUND_DOWN,
}


def _cached_singleton(key, model):
    value = cache.get(key)
    if value is None:
        value = model.objects.order_by("pk").first() or model()
        cache.set(key, value, timeout=None)
    return value


def get_system_configuration():
    return _cached_singleton(SYSTEM_CACHE_KEY, SystemConfiguration)


def get_organization_configuration():
    return _cached_singleton(ORGANIZATION_CACHE_KEY, OrganizationConfiguration)


def get_business_rules():
    return _cached_singleton(BUSINESS_RULES_CACHE_KEY, BusinessRules)


def configuration_values(instance, fields):
    values = {}
    for field in fields:
        value = getattr(instance, field)
        if field == "logo":
            value = value.name if value else ""
        values[field] = value
    return values


def save_configuration(*, instance, fields, user, entity_name):
    persisted = (
        instance.__class__.objects.filter(pk=instance.pk).first()
        if instance.pk
        else None
    )
    old_values = configuration_values(persisted, fields) if persisted else None
    instance.full_clean()
    instance.save()
    cache_key = {
        "SystemConfiguration": SYSTEM_CACHE_KEY,
        "OrganizationConfiguration": ORGANIZATION_CACHE_KEY,
        "BusinessRules": BUSINESS_RULES_CACHE_KEY,
    }[entity_name]
    cache.delete(cache_key)
    new_values = configuration_values(instance, fields)
    log_action(
        "Update" if old_values else "Create",
        entity_name,
        instance.pk,
        old_values=old_values,
        new_values=new_values,
    )
    return instance


def member_status_allowed(action, status):
    return status in get_business_rules().member_status_rules.get(action, [])


def configured_rounding():
    return ROUNDING_MODES[get_business_rules().rounding_mode]
