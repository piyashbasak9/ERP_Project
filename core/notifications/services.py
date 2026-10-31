import smtplib
from datetime import timedelta
from email.errors import MessageError

from django.contrib.auth import get_user_model
from django.db import models, transaction
from django.db.models import F, Q
from django.utils import timezone

from core.audit.services import log_action, record_system_event
from core.branch.models import MemberKYC
from core.loans.models import LoanApplication, LoanInstallment

from .models import (
    Notification,
    NotificationConfiguration,
    NotificationPreference,
    NotificationTemplate,
)
from .providers import provider_for

DEFAULT_TEMPLATES = {
    "installment_due": (
        "Installment due soon",
        "{member_name}: installment {reference} of {amount} is due on {due_date}.",
    ),
    "overdue": (
        "Installment overdue",
        "{member_name}: installment {reference} of {amount} was due on {due_date}.",
    ),
    "approval_waiting": (
        "Approval waiting",
        "Loan application {reference} is awaiting approval since {submitted_date}.",
    ),
    "kyc_expiry": (
        "KYC document expiry",
        "{member_name}'s {document_type} document expires on {expiry_date}.",
    ),
}


def _template(event_key):
    subject, body = DEFAULT_TEMPLATES[event_key]
    template, _ = NotificationTemplate.objects.get_or_create(
        event_key=event_key,
        defaults={"subject": subject, "body": body},
    )
    return template


def _branch_recipients(branch_id, event_key):
    User = get_user_model()
    recipients = User.objects.filter(
        branch_id=branch_id,
        is_active=True,
        user_role__isnull=False,
    ).order_by("pk")
    if event_key == "approval_waiting":
        recipients = recipients.filter(
            models.Q(
                user_role__role__permissions__route_name__icontains="approve"
            )
            | models.Q(
                user_role__role__permissions__route_name__icontains="review"
            ),
            user_role__role__permissions__is_active=True,
            user_role__role__permissions__is_allowed=True,
        )
    return recipients.distinct()


def _create_for_event(
    *, event_key, event_reference, branch_id, event_date, context
):
    template = _template(event_key)
    if not template.enabled:
        return 0
    rendered_subject = template.subject.format_map(context)
    rendered_body = template.body.format_map(context)
    created = 0
    for recipient in _branch_recipients(branch_id, event_key):
        preference, _ = NotificationPreference.objects.get_or_create(user=recipient)
        channels = []
        if preference.in_app_enabled:
            channels.append(Notification.CHANNEL_IN_APP)
        if preference.email_enabled and recipient.email:
            channels.append(Notification.CHANNEL_EMAIL)
        if preference.sms_enabled:
            channels.append(Notification.CHANNEL_SMS)
        for channel in channels:
            _, was_created = Notification.objects.get_or_create(
                recipient=recipient,
                event_key=event_key,
                event_reference=event_reference,
                event_date=event_date,
                channel=channel,
                defaults={
                    "branch_id": branch_id,
                    "subject": rendered_subject,
                    "body": rendered_body,
                    "status": (
                        Notification.STATUS_SENT
                        if channel == Notification.CHANNEL_IN_APP
                        else Notification.STATUS_PENDING
                    ),
                    "sent_at": timezone.now()
                    if channel == Notification.CHANNEL_IN_APP
                    else None,
                },
            )
            created += int(was_created)
    return created


def generate_daily_notifications(today=None):
    today = today or timezone.localdate()
    configuration = NotificationConfiguration.current()
    reminder_date = today + timedelta(days=configuration.installment_days_before)
    created = 0
    due_installments = LoanInstallment.objects.filter(
        due_date=reminder_date,
        schedule_version=F("loan__schedule_version"),
    ).select_related("loan__member", "loan__branch")
    for installment in due_installments:
        created += _create_for_event(
            event_key="installment_due",
            event_reference=f"installment:{installment.pk}",
            branch_id=installment.loan.branch_id,
            event_date=today,
            context={
                "branch_name": installment.loan.branch.name,
                "due_date": installment.due_date.isoformat(),
                "amount": str(installment.total_due),
                "member_name": installment.loan.member.full_name,
                "reference": f"{installment.loan_id}-{installment.number}",
                "days": configuration.installment_days_before,
            },
        )

    overdue_installments = LoanInstallment.objects.filter(
        due_date__lt=today,
        schedule_version=F("loan__schedule_version"),
    ).filter(
        Q(principal_paid__lt=F("principal_due"))
        | Q(interest_paid__lt=F("interest_due") - F("interest_waived"))
        | Q(fee_paid__lt=F("fee_due"))
    ).select_related("loan__member", "loan__branch")
    for installment in overdue_installments:
        created += _create_for_event(
            event_key="overdue",
            event_reference=f"installment:{installment.pk}",
            branch_id=installment.loan.branch_id,
            event_date=today,
            context={
                "branch_name": installment.loan.branch.name,
                "due_date": installment.due_date.isoformat(),
                "amount": str(installment.total_due),
                "member_name": installment.loan.member.full_name,
                "reference": f"{installment.loan_id}-{installment.number}",
                "days": (today - installment.due_date).days,
            },
        )

    approvals = LoanApplication.objects.filter(
        status=LoanApplication.STATUS_SUBMITTED
    ).select_related("branch")
    for application in approvals:
        created += _create_for_event(
            event_key="approval_waiting",
            event_reference=f"loan-application:{application.pk}",
            branch_id=application.branch_id,
            event_date=today,
            context={
                "branch_name": application.branch.name,
                "reference": str(application.pk),
                "submitted_date": application.updated_at.date().isoformat(),
            },
        )

    expiring_documents = MemberKYC.objects.filter(
        expiry_date=today,
    ).select_related("member__branch")
    for document in expiring_documents:
        created += _create_for_event(
            event_key="kyc_expiry",
            event_reference=f"kyc-document:{document.pk}",
            branch_id=document.member.branch_id,
            event_date=today,
            context={
                "branch_name": document.member.branch.name,
                "member_name": document.member.full_name,
                "document_type": document.get_document_type_display(),
                "expiry_date": today.isoformat(),
            },
        )
    return created


def dispatch_pending_notifications(*, now=None, limit=500):
    now = now or timezone.now()
    sent = 0
    failed = 0
    notification_ids = Notification.objects.filter(
        channel__in=(Notification.CHANNEL_EMAIL, Notification.CHANNEL_SMS),
        status=Notification.STATUS_PENDING,
    ).filter(
        models.Q(retry_at__isnull=True) | models.Q(retry_at__lte=now)
    ).order_by("created_at", "pk").values_list("pk", flat=True)[:limit]
    for notification_id in notification_ids:
        result = _dispatch_notification(notification_id, now)
        sent += int(result == "sent")
        failed += int(result == "failed")
    return {"sent": sent, "failed": failed}


@transaction.atomic
def _dispatch_notification(notification_id, now):
    notification = (
        Notification.objects.select_for_update(skip_locked=True)
        .select_related("recipient")
        .filter(
            pk=notification_id,
            status=Notification.STATUS_PENDING,
        )
        .first()
    )
    if notification is None:
        return "skipped"
    preference = NotificationPreference.objects.filter(
        user_id=notification.recipient_id
    ).first()
    enabled = (
        preference.email_enabled
        if notification.channel == Notification.CHANNEL_EMAIL and preference
        else preference.sms_enabled
        if notification.channel == Notification.CHANNEL_SMS and preference
        else True
    )
    if not enabled:
        notification.status = Notification.STATUS_CANCELLED
        notification.failure_code = "opted_out"
        notification.save(update_fields=("status", "failure_code"))
        return "skipped"
    try:
        provider_for(notification.channel).send(notification)
    except (OSError, smtplib.SMTPException, MessageError, ValueError):
        notification.attempts += 1
        notification.failure_code = "provider_error"
        if notification.attempts >= 5:
            notification.status = Notification.STATUS_FAILED
            notification.retry_at = None
        else:
            notification.retry_at = now + timedelta(
                hours=2 ** (notification.attempts - 1)
            )
        notification.save(
            update_fields=("attempts", "failure_code", "status", "retry_at")
        )
        record_system_event(
            category="integration",
            severity="error",
            message=f"Notification provider failed for channel {notification.channel}.",
        )
        return "failed"
    notification.status = Notification.STATUS_SENT
    notification.sent_at = now
    notification.failure_code = ""
    notification.save(update_fields=("status", "sent_at", "failure_code"))
    return "sent"


def run_notification_job(*, today=None, now=None):
    record_system_event(
        category="job",
        severity="info",
        status="started",
        message="Notification dispatch job started.",
    )
    try:
        generated = generate_daily_notifications(today=today)
        result = dispatch_pending_notifications(now=now)
    except Exception as error:
        record_system_event(
            category="job",
            severity="error",
            status="failed",
            message=f"Notification dispatch job failed: {type(error).__name__}.",
        )
        raise
    record_system_event(
        category="job",
        severity="info" if result["failed"] == 0 else "warning",
        status="completed",
        message=(
            f"Notification dispatch job completed: {generated} generated, "
            f"{result['sent']} sent, {result['failed']} failed."
        ),
    )
    return {"generated": generated, **result}


def mark_notification_read(*, notification_id, user, branch_ids):
    notification = Notification.objects.filter(
        pk=notification_id,
        recipient=user,
        branch_id__in=branch_ids,
        channel=Notification.CHANNEL_IN_APP,
    ).first()
    if notification is None:
        return False
    if not notification.is_read:
        notification.is_read = True
        notification.save(update_fields=("is_read",))
        log_action(
            "Read",
            "Notification",
            notification.pk,
            new_values={"is_read": True},
            branch_id=notification.branch_id,
        )
    return True
