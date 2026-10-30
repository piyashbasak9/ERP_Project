import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from core.common.managers import BranchScopedModel


def member_photo_path(instance, filename):
    return f"members/photos/{uuid.uuid4().hex}.jpg"


def member_kyc_path(instance, filename):
    return f"members/kyc/{uuid.uuid4().hex}"


class Branch(models.Model):
    BRANCH_TYPE_HEAD_OFFICE = "head_office"
    BRANCH_TYPE_REGION = "region"
    BRANCH_TYPE_AREA = "area"
    BRANCH_TYPE_BRANCH = "branch"

    BRANCH_TYPE_CHOICES = [
        (BRANCH_TYPE_HEAD_OFFICE, "Head Office"),
        (BRANCH_TYPE_REGION, "Region"),
        (BRANCH_TYPE_AREA, "Area"),
        (BRANCH_TYPE_BRANCH, "Branch"),
    ]

    class Meta:
        db_table = "branches"
        ordering = ["name"]

    objects = models.Manager()
    unscoped = models.Manager()

    name = models.CharField(max_length=100, db_index=True)
    code = models.CharField(max_length=20, unique=True, db_index=True)
    branch_type = models.CharField(
        max_length=20, choices=BRANCH_TYPE_CHOICES, default=BRANCH_TYPE_BRANCH
    )
    parent = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="children"
    )
    hierarchy_path = models.CharField(
        max_length=255, blank=True, default="", db_index=True
    )
    address = models.CharField(max_length=255, blank=True, default="")
    phone = models.CharField(max_length=30, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    opening_date = models.DateField(null=True, blank=True)
    business_date = models.DateField(default=timezone.localdate)
    branch_manager = models.ForeignKey(
        "branch.Staff",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="managed_branches",
    )
    is_active = models.BooleanField(default=True, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="branches_created",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="branches_updated",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def created_by_name(self):
        return self.created_by.username if self.created_by else None

    @property
    def updated_by_name(self):
        return self.updated_by.username if self.updated_by else None

    @property
    def ancestor_ids(self):
        if not self.hierarchy_path:
            return []
        cleaned = (
            self.hierarchy_path.strip("/").split("/")
            if self.hierarchy_path.strip("/")
            else []
        )
        return [int(item) for item in cleaned if item.isdigit()]

    def clean(self):
        if self.pk and self.parent_id == self.pk:
            raise ValidationError("A branch cannot be its own parent.")
        if self.parent_id:
            if self.parent.branch_type == self.BRANCH_TYPE_BRANCH:
                raise ValidationError(
                    {"parent": "A branch cannot contain another organization unit."}
                )
            if self.hierarchy_path and self.parent.hierarchy_path.startswith(
                self.hierarchy_path
            ):
                raise ValidationError(
                    {"parent": "Moving this unit would create a hierarchy cycle."}
                )
        elif self.branch_type in {self.BRANCH_TYPE_REGION, self.BRANCH_TYPE_AREA}:
            raise ValidationError({"parent": "Regions and areas must have a parent."})

    @classmethod
    def lock_hierarchy(cls):
        list(
            cls.unscoped.filter(parent__isnull=True)
            .order_by("pk")
            .select_for_update()
            .values_list("pk", flat=True)
        )

    def save(self, *args, **kwargs):
        old_hierarchy_path = None
        with transaction.atomic():
            Branch.lock_hierarchy()

            if self.pk:
                persisted = (
                    Branch.unscoped.select_for_update()
                    .filter(pk=self.pk)
                    .values("parent_id", "hierarchy_path")
                    .first()
                )
                if persisted:
                    old_hierarchy_path = persisted["hierarchy_path"]
                    self.hierarchy_path = old_hierarchy_path
                    update_fields = kwargs.get("update_fields")
                    if update_fields is not None and not {
                        "parent",
                        "parent_id",
                    }.intersection(update_fields):
                        self.parent_id = persisted["parent_id"]
                    self._state.fields_cache.pop("parent", None)
            else:
                self.hierarchy_path = ""

            self.full_clean()

            super().save(*args, **kwargs)

            if self.parent_id:
                parent_path = self.parent.hierarchy_path or f"/{self.parent_id}/"
                full_path = f"{parent_path.rstrip('/')}/{self.pk}/"
            else:
                full_path = f"/{self.pk}/"

            if self.hierarchy_path != full_path:
                Branch.unscoped.filter(pk=self.pk).update(hierarchy_path=full_path)
                self.hierarchy_path = full_path

            if old_hierarchy_path and old_hierarchy_path != full_path:
                descendants = (
                    Branch.unscoped.select_for_update()
                    .filter(
                        hierarchy_path__startswith=old_hierarchy_path,
                    )
                    .exclude(pk=self.pk)
                )
                for descendant in descendants:
                    new_descendant_path = (
                        full_path + descendant.hierarchy_path[len(old_hierarchy_path) :]
                    )
                    Branch.unscoped.filter(pk=descendant.pk).update(
                        hierarchy_path=new_descendant_path
                    )

    def __str__(self):
        return f"{self.name} ({self.code})"


class BranchHoliday(BranchScopedModel):
    class Meta:
        db_table = "branch_holidays"
        ordering = ["date", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["branch", "date"], name="uniq_branch_holiday_date"
            )
        ]

    date = models.DateField(db_index=True)
    name = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True, db_index=True)

    def __str__(self):
        return f"{self.name} ({self.date})"


class BranchClosedDay(models.Model):
    class Meta:
        db_table = "branch_closed_days"
        constraints = [
            models.UniqueConstraint(
                fields=["branch", "business_date"], name="uniq_branch_closed_date"
            )
        ]

    branch = models.ForeignKey(
        Branch, on_delete=models.PROTECT, related_name="closed_business_days"
    )
    business_date = models.DateField(db_index=True)
    is_closed = models.BooleanField(default=True, db_index=True)
    cash_count = models.DecimalField(max_digits=18, decimal_places=2)
    cash_difference_reason = models.CharField(max_length=500, blank=True, default="")
    carryover_note = models.CharField(max_length=500, blank=True, default="")
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="business_days_closed",
    )
    closed_at = models.DateTimeField(auto_now_add=True)
    reopened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="business_days_reopened",
    )
    reopened_at = models.DateTimeField(null=True, blank=True)
    reopen_reason = models.CharField(max_length=500, blank=True, default="")


class Center(BranchScopedModel):
    class Meta:
        db_table = "centers"
        ordering = ["name"]

    name = models.CharField(max_length=120)
    code = models.CharField(max_length=20, unique=True, db_index=True)
    meeting_day = models.CharField(max_length=20, blank=True, default="")
    meeting_time = models.CharField(max_length=20, blank=True, default="")
    location = models.CharField(max_length=255, blank=True, default="")
    field_officer = models.ForeignKey(
        "branch.Staff",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="centers",
    )
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.code})"


class Group(BranchScopedModel):
    class Meta:
        db_table = "member_groups"
        ordering = ["name"]

    center = models.ForeignKey(
        Center, on_delete=models.PROTECT, related_name="groups", null=True, blank=True
    )
    name = models.CharField(max_length=120)
    code = models.CharField(max_length=20, unique=True, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.code})"


class Staff(BranchScopedModel):
    class Meta:
        db_table = "staff"
        ordering = ["full_name"]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="staff_profile",
    )
    full_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=30, blank=True, default="")
    designation = models.CharField(max_length=100, blank=True, default="")
    assigned_centers = models.ManyToManyField(
        "branch.Center",
        blank=True,
        related_name="assigned_staff",
    )
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.full_name


class Member(BranchScopedModel):
    STATUS_ACTIVE = "active"
    STATUS_INACTIVE = "inactive"
    STATUS_PENDING = "pending"
    STATUS_SUSPENDED = "suspended"

    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_INACTIVE, "Inactive"),
        (STATUS_PENDING, "Pending"),
        (STATUS_SUSPENDED, "Suspended"),
    ]

    class Meta:
        db_table = "members"
        ordering = ["first_name", "last_name"]

    center = models.ForeignKey(
        "branch.Center",
        on_delete=models.PROTECT,
        related_name="members",
        null=True,
        blank=True,
    )
    group = models.ForeignKey(
        Group, on_delete=models.PROTECT, related_name="members", null=True, blank=True
    )
    member_code = models.CharField(max_length=30, unique=True, db_index=True)
    first_name = models.CharField(max_length=80)
    last_name = models.CharField(max_length=80)
    father_name = models.CharField(max_length=150, blank=True, default="")
    mother_name = models.CharField(max_length=150, blank=True, default="")
    spouse_name = models.CharField(max_length=150, blank=True, default="")
    phone = models.CharField(max_length=30, blank=True, default="")
    alternate_phone = models.CharField(max_length=30, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    national_id = models.CharField(max_length=40, blank=True, default="")
    other_id_numbers = models.CharField(max_length=255, blank=True, default="")
    gender = models.CharField(max_length=20, blank=True, default="")
    marital_status = models.CharField(max_length=20, blank=True, default="")
    date_of_birth = models.DateField(null=True, blank=True)
    present_address = models.CharField(max_length=255, blank=True, default="")
    permanent_address = models.CharField(max_length=255, blank=True, default="")
    occupation = models.CharField(max_length=100, blank=True, default="")
    monthly_income = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    household_size = models.PositiveSmallIntegerField(null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING
    )
    photo = models.ImageField(upload_to=member_photo_path, blank=True, null=True)
    admission_date = models.DateField(default=timezone.localdate)
    admission_fee = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    joined_at = models.DateField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="members_created",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="members_updated",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    def clean(self):
        if (
            self.branch_id
            and self.center_id
            and self.center.branch_id != self.branch_id
        ):
            raise ValidationError(
                {"center": "The center must belong to the member branch."}
            )
        if self.branch_id and self.group_id and self.group.branch_id != self.branch_id:
            raise ValidationError(
                {"group": "The group must belong to the member branch."}
            )
        if (
            self.center_id
            and self.group_id
            and self.group.center_id not in {None, self.center_id}
        ):
            raise ValidationError(
                {"group": "The group must belong to the selected center."}
            )
        if self.monthly_income is not None and self.monthly_income < 0:
            raise ValidationError(
                {"monthly_income": "Monthly income cannot be negative."}
            )
        if self.admission_fee < 0:
            raise ValidationError(
                {"admission_fee": "Admission fee cannot be negative."}
            )

    def __str__(self):
        return self.full_name or self.member_code


class MemberNominee(models.Model):
    class Meta:
        db_table = "member_nominees"

    member = models.ForeignKey(
        Member, on_delete=models.CASCADE, related_name="nominees"
    )
    name = models.CharField(max_length=150)
    relationship = models.CharField(max_length=80)
    phone = models.CharField(max_length=30, blank=True, default="")
    identification_number = models.CharField(max_length=50, blank=True, default="")
    share_percentage = models.DecimalField(max_digits=5, decimal_places=2)

    def clean(self):
        if self.share_percentage < 0 or self.share_percentage > 100:
            raise ValidationError(
                {"share_percentage": "Share must be between 0 and 100."}
            )


class MemberKYC(models.Model):
    DOC_TYPE_NATIONAL_ID = "national_id"
    DOC_TYPE_PHOTO = "photo"
    DOC_TYPE_ADDRESS = "address"
    DOC_TYPE_OTHER = "other"

    DOC_TYPE_CHOICES = [
        (DOC_TYPE_NATIONAL_ID, "National ID"),
        (DOC_TYPE_PHOTO, "Photo"),
        ("birth_certificate", "Birth Certificate"),
        ("passport", "Passport"),
        ("driving_license", "Driving License"),
        (DOC_TYPE_ADDRESS, "Address"),
        (DOC_TYPE_OTHER, "Other"),
    ]

    STATUS_PENDING = "pending"
    STATUS_VERIFIED = "verified"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_VERIFIED, "Verified"),
        (STATUS_REJECTED, "Rejected"),
    ]

    class Meta:
        db_table = "member_kyc"
        ordering = ["-uploaded_at"]

    member = models.ForeignKey(
        Member, on_delete=models.CASCADE, related_name="kyc_documents"
    )
    document_type = models.CharField(
        max_length=30, choices=DOC_TYPE_CHOICES, default=DOC_TYPE_NATIONAL_ID
    )
    file = models.FileField(upload_to=member_kyc_path, blank=True, null=True)
    file_name = models.CharField(max_length=200, blank=True, default="")
    mime_type = models.CharField(max_length=50, blank=True, default="")
    document_number = models.CharField(max_length=80, blank=True, default="")
    issue_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True
    )
    is_verified = models.BooleanField(default=False, db_index=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="kyc_documents_verified",
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.CharField(max_length=255, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        if self.expiry_date and self.issue_date and self.expiry_date < self.issue_date:
            raise ValidationError(
                {"expiry_date": "Expiry date cannot be before issue date."}
            )
        if self.status == self.STATUS_REJECTED and not self.rejection_reason.strip():
            raise ValidationError(
                {"rejection_reason": "A reason is required when rejecting a document."}
            )

    def __str__(self):
        return f"{self.member_id} - {self.document_type}"


class MemberStatusHistory(models.Model):
    class Meta:
        db_table = "member_status_history"
        ordering = ["-created_at"]

    member = models.ForeignKey(
        Member, on_delete=models.PROTECT, related_name="status_history"
    )
    old_status = models.CharField(max_length=20, choices=Member.STATUS_CHOICES)
    new_status = models.CharField(max_length=20, choices=Member.STATUS_CHOICES)
    reason = models.CharField(max_length=255)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)


class UserBranchAccess(models.Model):
    class Meta:
        db_table = "user_branch_access"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "branch"], name="uniq_user_branch_access"
            ),
        ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="branch_access"
    )
    branch = models.ForeignKey(
        Branch, on_delete=models.CASCADE, related_name="user_access"
    )
