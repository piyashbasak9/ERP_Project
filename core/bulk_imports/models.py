import uuid

from django.conf import settings
from django.db import models


def private_import_path(instance, filename):
    return f"imports/{uuid.uuid4().hex}.xlsx"


class ImportBatch(models.Model):
    TYPE_MEMBERS = "members"
    TYPE_SAVINGS_OPENING = "savings_opening"
    TYPE_GL_OPENING = "gl_opening"
    TYPE_CHOICES = [
        (TYPE_MEMBERS, "Members"),
        (TYPE_SAVINGS_OPENING, "Savings opening balances"),
        (TYPE_GL_OPENING, "GL opening balances"),
    ]
    STATUS_UPLOADED = "uploaded"
    STATUS_VALIDATED = "validated"
    STATUS_INVALID = "invalid"
    STATUS_AWAITING_APPROVAL = "awaiting_approval"
    STATUS_IMPORTED = "imported"
    STATUS_CHOICES = [
        (STATUS_UPLOADED, "Uploaded"),
        (STATUS_VALIDATED, "Validated"),
        (STATUS_INVALID, "Invalid"),
        (STATUS_AWAITING_APPROVAL, "Awaiting approval"),
        (STATUS_IMPORTED, "Imported"),
    ]

    branch = models.ForeignKey("branch.Branch", on_delete=models.PROTECT)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="imports_created",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="imports_approved",
    )
    import_type = models.CharField(max_length=24, choices=TYPE_CHOICES)
    file_hash = models.CharField(max_length=64, unique=True)
    source_name = models.CharField(max_length=255)
    source_file = models.FileField(upload_to=private_import_path)
    status = models.CharField(
        max_length=24, choices=STATUS_CHOICES, default=STATUS_UPLOADED, db_index=True
    )
    validation_errors = models.JSONField(default=list, blank=True)
    row_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    imported_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "import_batches"
        ordering = ["-created_at", "-pk"]

