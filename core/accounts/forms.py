from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.db import transaction

from core.branch.models import Branch, UserBranchAccess

from .models import Permission, Role, RolePermission
from .permission_utils import get_all_urls

User = get_user_model()


class RoleForm(forms.Form):
    name = forms.CharField(
        max_length=50,
        label='Role Name',
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    url_permissions = forms.MultipleChoiceField(
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'url-checkbox-list'}),
        label='URL Permissions',
    )

    def __init__(self, *args, **kwargs):
        self.role_id = kwargs.pop('role_id', None)
        super().__init__(*args, **kwargs)

        all_urls = get_all_urls()
        choices = [(item['route_name'], item['route_name']) for item in all_urls]
        self.fields['url_permissions'].choices = choices

        if self.role_id:
            try:
                role = Role.objects.get(pk=self.role_id)
            except Role.DoesNotExist:
                return
            self.fields['name'].initial = role.name
            allowed_urls = list(
                role.permissions.filter(is_allowed=True, is_active=True)
                .values_list('route_name', flat=True)
            )
            self.fields['url_permissions'].initial = allowed_urls

    def save(self):
        name = self.cleaned_data['name']
        selected_urls = self.cleaned_data['url_permissions']

        if self.role_id:
            existing_by_name = Role.objects.filter(name=name).exclude(pk=self.role_id).exists()
            if existing_by_name:
                raise ValueError('Role with this name already exists.')
            role = Role.objects.get(pk=self.role_id)
            role.name = name
            role.save()
        else:
            if Role.objects.filter(name=name).exists():
                raise ValueError('Role with this name already exists.')
            role = Role.objects.create(name=name)

        role.role_permissions.all().delete()
        routes_by_name = {
            route['route_name']: route
            for route in get_all_urls()
        }
        for route_name in selected_urls:
            route = routes_by_name[route_name]
            permission, _ = Permission.objects.update_or_create(
                route_name=route_name,
                defaults={
                    'url_pattern': route['url'],
                    'is_allowed': True,
                    'is_active': True,
                    'module': route['module'],
                    'action': route['action'],
                    'description': route['description'],
                },
            )
            RolePermission.objects.update_or_create(
                role=role,
                permission=permission,
                defaults={},
            )

        return {'id': role.id, 'name': role.name}


class UserCreationForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-control'}), label='Password')
    confirm_password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-control'}), label='Confirm Password')
    role_id = forms.ChoiceField(
        required=False,
        label='Assign Role',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    accessible_branches = forms.ModelMultipleChoiceField(
        required=False,
        queryset=Branch.unscoped.none(),
        label='Additional branch access',
        widget=forms.SelectMultiple(attrs={'class': 'form-select'}),
    )

    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name', 'branch']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'branch': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, request, **kwargs):
        super().__init__(*args, **kwargs)
        allowed_branch_ids = request.user.accessible_branch_ids(request.active_branch_id)
        allowed_branches = Branch.unscoped.filter(pk__in=allowed_branch_ids, is_active=True)
        self.fields['branch'].queryset = allowed_branches
        self.fields['branch'].required = False
        self.fields['accessible_branches'].queryset = allowed_branches
        roles = Role.objects.all()
        choices = [('', '--------- Select Role ---------')] + [(role.id, role.name) for role in roles]
        self.fields['role_id'].choices = choices

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        confirm = cleaned_data.get('confirm_password')
        if password and confirm and password != confirm:
            raise forms.ValidationError('Passwords do not match!')
        if password:
            validate_password(password, self.instance)
        return cleaned_data

    @transaction.atomic
    def save_branch_access(self, user):
        explicit_ids = set(self.cleaned_data['accessible_branches'].values_list('pk', flat=True))
        if user.branch_id:
            explicit_ids.discard(user.branch_id)
        current_ids = set(
            UserBranchAccess.objects.filter(user=user).values_list('branch_id', flat=True)
        )
        UserBranchAccess.objects.filter(user=user, branch_id__in=current_ids - explicit_ids).delete()
        UserBranchAccess.objects.bulk_create(
            [
                UserBranchAccess(user=user, branch_id=branch_id)
                for branch_id in explicit_ids - current_ids
            ],
            ignore_conflicts=True,
        )


class UserEditForm(forms.ModelForm):
    role_id = forms.ChoiceField(
        required=False,
        label='Assign Role',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    accessible_branches = forms.ModelMultipleChoiceField(
        required=False,
        queryset=Branch.unscoped.none(),
        label='Additional branch access',
        widget=forms.SelectMultiple(attrs={'class': 'form-select'}),
    )

    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name', 'branch']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'branch': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, request, **kwargs):
        super().__init__(*args, **kwargs)
        allowed_branch_ids = request.user.accessible_branch_ids(request.active_branch_id)
        allowed_branches = Branch.unscoped.filter(pk__in=allowed_branch_ids, is_active=True)
        self.fields['branch'].queryset = allowed_branches
        self.fields['branch'].required = False
        self.fields['accessible_branches'].queryset = allowed_branches
        roles = Role.objects.all()
        self.fields['role_id'].choices = [('', '--------- No Role ---------')] + [
            (role.id, role.name) for role in roles
        ]
        user_role = getattr(self.instance, 'user_role', None)
        if user_role:
            self.fields['role_id'].initial = user_role.role_id
        self.fields['accessible_branches'].initial = (
            UserBranchAccess.objects.filter(user=self.instance)
            .exclude(branch_id=self.instance.branch_id)
            .values_list('branch_id', flat=True)
        )

    @transaction.atomic
    def save_branch_access(self, user):
        explicit_ids = set(self.cleaned_data['accessible_branches'].values_list('pk', flat=True))
        if user.branch_id:
            explicit_ids.discard(user.branch_id)
        current_ids = set(
            UserBranchAccess.objects.filter(user=user).values_list('branch_id', flat=True)
        )
        UserBranchAccess.objects.filter(user=user, branch_id__in=current_ids - explicit_ids).delete()
        UserBranchAccess.objects.bulk_create(
            [
                UserBranchAccess(user=user, branch_id=branch_id)
                for branch_id in explicit_ids - current_ids
            ],
            ignore_conflicts=True,
        )
