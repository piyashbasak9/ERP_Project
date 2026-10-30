from datetime import datetime
from decimal import Decimal

from django import template
from django.utils import timezone

from core.configuration.services import get_system_configuration

register = template.Library()


@register.filter
def user_date(value, preference=None):
    if not value:
        return ""
    date_format = (
        preference.date_format
        if preference
        else get_system_configuration().date_format
    )
    if isinstance(value, datetime) and timezone.is_aware(value):
        value = timezone.localtime(value)
    return value.strftime(date_format)


@register.filter
def config_money(value, configuration=None):
    if value is None:
        return ""
    configuration = configuration or get_system_configuration()
    amount = Decimal(str(value)).quantize(Decimal("0.01"))
    sign = "-" if amount < 0 else ""
    whole, fractional = f"{abs(amount):.2f}".split(".")
    if configuration.number_format == "indian" and len(whole) > 3:
        tail = whole[-3:]
        prefix = whole[:-3]
        groups = []
        while prefix:
            groups.insert(0, prefix[-2:])
            prefix = prefix[:-2]
        whole = ",".join(groups + [tail])
    else:
        whole = f"{int(whole):,}"
    return f"{configuration.currency_symbol}{sign}{whole}.{fractional}"
