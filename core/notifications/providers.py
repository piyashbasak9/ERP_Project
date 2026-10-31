import logging
import smtplib
from abc import ABC, abstractmethod

from django.conf import settings
from django.core.mail import send_mail

from .models import Notification

logger = logging.getLogger(__name__)


class EmailProvider:
    def send(self, notification):
        recipient_email = notification.recipient.email
        if not recipient_email:
            raise ValueError("The notification recipient has no email address.")
        sent = send_mail(
            notification.subject,
            notification.body,
            settings.DEFAULT_FROM_EMAIL,
            [recipient_email],
            fail_silently=False,
        )
        if sent != 1:
            raise smtplib.SMTPException("Email provider did not accept the notification.")


class SMSProvider(ABC):
    @abstractmethod
    def send(self, notification):
        raise NotImplementedError("SMS providers must implement send().")


class ConsoleSMSProvider(SMSProvider):
    def send(self, notification):
        logger.info("SMS delivery simulated for notification id %s.", notification.pk)


class NotificationProviderError(Exception):
    pass


def provider_for(channel):
    if channel == Notification.CHANNEL_EMAIL:
        return EmailProvider()
    if channel == Notification.CHANNEL_SMS:
        return ConsoleSMSProvider()
    raise NotificationProviderError("In-app notifications are not sent through a provider.")
