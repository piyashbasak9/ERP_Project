from django.db import models

from .context import current_branch_id_var, current_user_var


class BranchScopedQuerySet(models.QuerySet):
    def for_user(self, user, active_branch_id=None):
        branch_ids = user.accessible_branch_ids(active_branch_id)
        return self.filter(branch_id__in=branch_ids)


class BranchScopedManager(models.Manager.from_queryset(BranchScopedQuerySet)):
    def get_queryset(self):
        queryset = super().get_queryset()
        user = current_user_var.get()
        if user is None or not user.is_authenticated:
            return queryset.none()
        return queryset.for_user(user, current_branch_id_var.get())


class BranchScopedModel(models.Model):
    branch = models.ForeignKey(
        'branch.Branch',
        on_delete=models.PROTECT,
        related_name='%(app_label)s_%(class)s_records',
    )
    version = models.PositiveIntegerField(default=1)
    objects = BranchScopedManager()
    unscoped = models.Manager()

    class Meta:
        abstract = True
