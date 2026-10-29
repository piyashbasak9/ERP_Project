from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import Branch, Center, Member, Staff


class BranchReadService:
    def __init__(self, request):
        self.request = request

    def search(self, queryset):
        if self.request.GET.get("name"):
            queryset = queryset.filter(name__icontains=self.request.GET.get("name"))

        if self.request.GET.get("code"):
            queryset = queryset.filter(code__icontains=self.request.GET.get("code"))

        return queryset

    def all(self):
        queryset = self._scoped_queryset().filter(is_active=True)
        return self.search(queryset).order_by("name")

    def get(self, branch_id):
        return self._scoped_queryset().filter(is_active=True, pk=branch_id).first()

    def _scoped_queryset(self):
        queryset = Branch.unscoped.all()
        user = getattr(self.request, "user", None)
        if not user or not user.is_authenticated:
            return queryset.none()
        return queryset.filter(
            pk__in=user.accessible_branch_ids(
                getattr(self.request, "active_branch_id", None)
            )
        )


class BranchWriteService:
    def __init__(self, request):
        self.request = request

    @transaction.atomic
    def create(self, data):
        Branch.lock_hierarchy()
        branch = Branch(**data)
        self._validate_parent_access(branch)
        branch.created_by = self.request.user
        branch.updated_by = self.request.user
        branch.full_clean()
        branch.save()
        return branch

    @transaction.atomic
    def update(self, branch_id, data):
        Branch.lock_hierarchy()
        branch = (
            self._scoped_queryset()
            .select_for_update()
            .filter(is_active=True, pk=branch_id)
            .first()
        )
        if not branch:
            return None

        for key, value in data.items():
            setattr(branch, key, value)
        branch.updated_by = self.request.user
        self._validate_parent_access(branch)
        branch.save()

        return branch

    @transaction.atomic
    def delete(self, id):
        Branch.lock_hierarchy()
        branch = (
            self._scoped_queryset()
            .select_for_update()
            .filter(is_active=True, pk=id)
            .first()
        )
        if not branch:
            return None

        if branch.children.filter(is_active=True).exists():
            raise ValidationError(
                "A branch with active child units cannot be deactivated."
            )
        if Center.unscoped.filter(branch=branch, is_active=True).exists():
            raise ValidationError("A branch with active centers cannot be deactivated.")
        if (
            Member.unscoped.filter(branch=branch)
            .exclude(status=Member.STATUS_INACTIVE)
            .exists()
        ):
            raise ValidationError("A branch with active members cannot be deactivated.")
        if Staff.unscoped.filter(branch=branch, is_active=True).exists():
            raise ValidationError("A branch with active staff cannot be deactivated.")

        branch.is_active = False
        branch.updated_at = timezone.now()
        if getattr(self.request, "user", None) and getattr(
            self.request.user, "is_authenticated", False
        ):
            branch.updated_by_id = self.request.user.id
        branch.save(update_fields=["is_active", "updated_at", "updated_by"])
        return branch

    def _scoped_queryset(self):
        user = getattr(self.request, "user", None)
        queryset = Branch.unscoped.all()
        if not user or not user.is_authenticated:
            return queryset.none()
        return queryset.filter(
            pk__in=user.accessible_branch_ids(
                getattr(self.request, "active_branch_id", None)
            )
        )

    def _validate_parent_access(self, branch):
        if (
            branch.parent_id
            and not self._scoped_queryset().filter(pk=branch.parent_id).exists()
        ):
            raise ValidationError(
                {
                    "parent": "You cannot assign a parent outside your accessible branches."
                }
            )
