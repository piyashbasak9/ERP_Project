from django.conf import settings
from django.db import models


class ImmutableAuditQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise TypeError('Audit records are immutable.')

    def delete(self):
        raise TypeError('Audit records are immutable.')


class AuditLog(models.Model):
    class Meta:
        db_table = 'audit_logs'
        ordering = ['-timestamp_utc']
        indexes = [
            models.Index(fields=['entity_name', 'entity_id'], name='audit_entity_idx'),
            models.Index(fields=['user', 'timestamp_utc'], name='audit_user_time_idx'),
        ]

    timestamp_utc = models.DateTimeField(auto_now_add=True, db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    user_name = models.CharField(max_length=150, blank=True, default='')
    role_name = models.CharField(max_length=50, blank=True, default='')
    branch = models.ForeignKey('branch.Branch', on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=40, db_index=True)
    entity_name = models.CharField(max_length=100, db_index=True)
    entity_id = models.CharField(max_length=100, blank=True, default='')
    old_values = models.JSONField(null=True, blank=True)
    new_values = models.JSONField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True, default='')
    correlation_id = models.CharField(max_length=64, blank=True, default='', db_index=True)
    remarks = models.CharField(max_length=500, blank=True, default='')

    objects = ImmutableAuditQuerySet.as_manager()

    def save(self, *args, **kwargs):
        if self.pk:
            raise TypeError('Audit records are immutable.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError('Audit records are immutable.')
