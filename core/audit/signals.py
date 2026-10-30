from axes.signals import user_locked_out
from django.contrib.auth import get_user_model
from django.contrib.auth.signals import (
    user_logged_in,
    user_logged_out,
    user_login_failed,
)
from django.db.models.signals import post_delete, post_save, pre_save

from core.accounts.models import Permission, Role, RolePermission, UserRole

from .context import audit_context_var
from .services import log_action

AUDITED_MODELS = (Role, Permission, RolePermission, UserRole)


def _values(instance):
    result = {}
    for field in instance._meta.concrete_fields:
        if field.primary_key:
            continue
        key = field.attname
        value = getattr(instance, key)
        if value is not None and not isinstance(value, (str, int, float, bool)):
            value = str(value)
        result[key] = value
    return result


def _active_context():
    context = audit_context_var.get() or {}
    return context if context.get("user") else None


def _pre_save(sender, instance, **kwargs):
    if not _active_context() or not instance.pk:
        instance._audit_old_values = None
        return
    previous = sender.objects.filter(pk=instance.pk).first()
    instance._audit_old_values = _values(previous) if previous else None


def _post_save(sender, instance, created, **kwargs):
    if not _active_context():
        return
    log_action(
        "Create" if created else "Update",
        sender.__name__,
        instance.pk,
        old_values=None if created else getattr(instance, "_audit_old_values", None),
        new_values=_values(instance),
    )


def _post_delete(sender, instance, **kwargs):
    if _active_context():
        log_action(
            "Delete",
            sender.__name__,
            instance.pk,
            old_values=_values(instance),
        )


def _login(sender, request, user, **kwargs):
    branch_id = user.branch_id
    log_action("Login", "User", user.pk, new_values={"username": user.get_username()}, branch_id=branch_id)


def _logout(sender, request, user, **kwargs):
    if user:
        log_action("Logout", "User", user.pk, new_values={"username": user.get_username()}, branch_id=user.branch_id)


def _login_failed(sender, credentials, request, **kwargs):
    username = str(credentials.get("username", ""))[:150]
    branch_id = None
    if username:
        branch_id = (
            get_user_model().objects.filter(username=username)
            .values_list("branch_id", flat=True)
            .first()
        )
    log_action(
        "LoginFailed",
        "User",
        username,
        new_values={"username": username},
        branch_id=branch_id,
    )


def _lockout(sender, request, username=None, ip_address=None, **kwargs):
    username = str(username or "")[:150]
    branch_id = (
        get_user_model().objects.filter(username=username)
        .values_list("branch_id", flat=True)
        .first()
        if username
        else None
    )
    log_action(
        "Lockout",
        "User",
        username,
        new_values={"username": username, "ip_address": ip_address},
        branch_id=branch_id,
    )


def register():
    for model in AUDITED_MODELS:
        pre_save.connect(_pre_save, sender=model, weak=False, dispatch_uid=f"audit-pre-{model._meta.label_lower}")
        post_save.connect(_post_save, sender=model, weak=False, dispatch_uid=f"audit-post-{model._meta.label_lower}")
        post_delete.connect(_post_delete, sender=model, weak=False, dispatch_uid=f"audit-delete-{model._meta.label_lower}")
    user_logged_in.connect(_login, weak=False, dispatch_uid="audit-login")
    user_logged_out.connect(_logout, weak=False, dispatch_uid="audit-logout")
    user_login_failed.connect(_login_failed, weak=False, dispatch_uid="audit-login-failed")
    user_locked_out.connect(_lockout, weak=False, dispatch_uid="audit-lockout")
