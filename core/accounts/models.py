from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models


class CustomUser(AbstractUser):
    branch = models.ForeignKey(
        'branch.Branch',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='users',
    )

    class Meta:
        db_table = 'auth_user'

    def accessible_branch_ids(self, active_branch_id=None):
        from django.apps import apps

        Branch = apps.get_model('branch', 'Branch')
        UserBranchAccess = apps.get_model('branch', 'UserBranchAccess')

        if self.is_superuser:
            branch_ids = set(Branch.unscoped.values_list('id', flat=True))
        else:
            branch_ids = set()
            if self.branch_id:
                root_path = (
                    Branch.unscoped.filter(pk=self.branch_id)
                    .values_list('hierarchy_path', flat=True)
                    .first()
                )
                if root_path:
                    branch_ids.update(
                        Branch.unscoped.filter(hierarchy_path__startswith=root_path).values_list(
                            'id', flat=True
                        )
                    )
                else:
                    branch_ids.add(self.branch_id)
            branch_ids.update(
                UserBranchAccess.objects.filter(user_id=self.pk).values_list('branch_id', flat=True)
            )

        if active_branch_id is not None:
            if active_branch_id not in branch_ids:
                return set()
            active_path = (
                Branch.unscoped.filter(pk=active_branch_id)
                .values_list('hierarchy_path', flat=True)
                .first()
            )
            if active_path:
                active_ids = set(
                    Branch.unscoped.filter(hierarchy_path__startswith=active_path).values_list(
                        'id', flat=True
                    )
                )
                branch_ids.intersection_update(active_ids)
            else:
                branch_ids.intersection_update({active_branch_id})

        return branch_ids

    def __str__(self):
        return self.username


class Permission(models.Model):
    class Meta:
        db_table = 'permissions'
        ordering = ['route_name']

    route_name = models.CharField(max_length=255, unique=True, null=True, blank=True, db_index=True)
    url_pattern = models.CharField(max_length=255, unique=True, db_index=True)
    is_allowed = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True, db_index=True)
    module = models.CharField(max_length=80, blank=True, default='')
    action = models.CharField(max_length=40, blank=True, default='')
    description = models.CharField(max_length=255, null=True, blank=True)

    def __str__(self):
        return self.route_name or self.url_pattern


class Role(models.Model):
    class Meta:
        db_table = 'roles'

    name = models.CharField(max_length=50, unique=True)
    permissions = models.ManyToManyField('Permission', through='RolePermission', related_name='roles')

    def __str__(self):
        return self.name


class RolePermission(models.Model):
    class Meta:
        db_table = 'role_permissions'
        unique_together = ('role', 'permission')

    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name='role_permissions')
    permission = models.ForeignKey(Permission, on_delete=models.CASCADE, related_name='role_permissions')

    def __str__(self):
        return f'{self.role_id}:{self.permission_id}'


class UserRole(models.Model):
    class Meta:
        db_table = 'user_roles'

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='user_role')
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name='user_roles')

    @property
    def role_name(self):
        return self.role.name if self.role else None

    def __str__(self):
        return f'{self.user_id} -> {self.role_id}'
