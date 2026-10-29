from django.contrib import messages
from django.contrib.auth import get_user_model, logout
from django.contrib.auth.views import LoginView, LogoutView
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.decorators.http import require_POST

from .forms import RoleForm, UserCreationForm, UserEditForm
from .models import Role, UserRole

User = get_user_model()


def create_role(request):
    if request.method == 'POST':
        form = RoleForm(request.POST)
        if form.is_valid():
            try:
                role = form.save()
            except (IntegrityError, ValueError) as exc:
                form.add_error('name', str(exc))
                messages.error(request, str(exc))
            else:
                role_name = role.get('name') if isinstance(role, dict) else getattr(role, 'name', str(role))
                messages.success(request, f"✅ '{role_name}' Successfully created!")
                if request.GET.get('popup') == '1':
                    return render(request, 'popup_complete.html', {
                        'completion_message': f"'{role_name}' created successfully.",
                    })
                return redirect('accounts:Module_Auth_list_roles')
        else:
            messages.error(request, 'Form is not valid.')
    else:
        form = RoleForm()
    return render(request, 'accounts/create_role.html', {'form': form})


def edit_role(request, pk):
    try:
        role = Role.objects.get(pk=pk)
    except Role.DoesNotExist:
        messages.error(request, 'Role not found.')
        return redirect('accounts:Module_Auth_list_roles')

    role_data = {'id': role.id, 'name': role.name}

    if request.method == 'POST':
        form = RoleForm(request.POST, role_id=pk)
        if form.is_valid():
            try:
                form.save()
            except (IntegrityError, ValueError) as exc:
                messages.error(request, f'Could not update role: {exc}')
            else:
                messages.success(request, f"✅ '{role_data.get('name')}' updated successfully!")
                if request.GET.get('popup') == '1':
                    return render(request, 'popup_complete.html', {
                        'completion_message': f"'{role_data.get('name')}' updated successfully.",
                    })
                return redirect('accounts:Module_Auth_list_roles')
    else:
        form = RoleForm(role_id=pk)

    return render(request, 'accounts/edit_role.html', {'form': form, 'role': role_data})


def create_user(request):
    form = UserCreationForm(request.POST or None, request=request)
    if request.method == 'POST':
        if form.is_valid():
            with transaction.atomic():
                user = form.save(commit=False)
                user.set_password(form.cleaned_data['password'])
                user.save()
                form.save_branch_access(user)
                role_id = form.cleaned_data.get('role_id')
                if role_id:
                    UserRole.objects.update_or_create(
                        user=user,
                        defaults={'role_id': int(role_id)},
                    )
            completion_message = f"'{user.username}' created successfully."
            if role_id:
                messages.success(request, f"'{user.username}' created and role assigned successfully!")
            else:
                messages.warning(request, 'User created, but no role assigned.')

            if request.GET.get('popup') == '1':
                return render(request, 'popup_complete.html', {
                    'completion_message': completion_message,
                })
            return redirect('accounts:Module_Auth_list_users')
        messages.error(request, 'Form is not valid.')
    return render(request, 'accounts/create_user.html', {'form': form})


def list_roles(request):
    roles = Role.objects.prefetch_related('permissions').all()
    roles_list = [{
        'id': role.id,
        'name': role.name,
        'perm_count': role.permissions.count(),
    } for role in roles]
    return render(request, 'accounts/list_roles.html', {'roles': roles_list})


def list_users(request):
    manageable_user_ids = [
        user.pk
        for user in users_visible_to(request).only('id', 'branch_id')
        if user_access_is_manageable(request, user)
    ]
    users = User.objects.filter(pk__in=manageable_user_ids).values(
        'id', 'username', 'email', 'first_name', 'last_name'
    )
    user_roles = UserRole.objects.select_related('role').filter(user_id__in=users.values('id'))
    role_map = {record.user_id: record.role.name for record in user_roles if record.role}
    for user in users:
        user['role'] = role_map.get(user['id'], 'No Role')
    return render(request, 'accounts/list_users.html', {'users': users})


def edit_user(request, pk):
    user = get_object_or_404(users_visible_to(request), pk=pk)
    if not user_access_is_manageable(request, user):
        raise Http404
    form = UserEditForm(request.POST or None, instance=user, request=request)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            user = form.save()
            form.save_branch_access(user)
            role_id = form.cleaned_data['role_id']
            if role_id:
                UserRole.objects.update_or_create(
                    user=user,
                    defaults={'role_id': int(role_id)},
                )
            else:
                UserRole.objects.filter(user=user).delete()
        messages.success(request, f"'{user.username}' updated successfully!")
        if request.GET.get('popup') == '1':
            return render(request, 'popup_complete.html', {
                'completion_message': f"'{user.username}' updated successfully.",
            })
        return redirect('accounts:Module_Auth_list_users')
    return render(request, 'accounts/edit_user.html', {'user': user, 'form': form})


@require_POST
def delete_user(request, pk):
    user = get_object_or_404(users_visible_to(request), pk=pk)
    if not user_access_is_manageable(request, user):
        raise Http404
    if user.pk == request.user.pk:
        return JsonResponse({'success': False, 'message': 'You cannot delete your own account.'}, status=400)
    username = user.username
    user.delete()
    completion_message = f"'{username}' deleted successfully."
    messages.success(request, completion_message)

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'success': True, 'message': completion_message})
    return redirect('accounts:Module_Auth_list_users')


def users_visible_to(request):
    if request.user.is_superuser:
        return User.objects.all()
    accessible_branch_ids = request.user.accessible_branch_ids(request.active_branch_id)
    return (
        User.objects.filter(
            Q(branch_id__in=accessible_branch_ids)
            | Q(branch_access__branch_id__in=accessible_branch_ids),
            is_superuser=False,
        )
        .distinct()
    )


def user_access_is_manageable(request, user):
    if request.user.is_superuser:
        return True
    return user.accessible_branch_ids().issubset(
        request.user.accessible_branch_ids(request.active_branch_id)
    )


class CustomLoginView(LoginView):
    template_name = 'registration/login.html'
    redirect_authenticated_user = True

    def get_success_url(self):
        return super().get_success_url()


class CustomLogoutView(LogoutView):
    next_page = reverse_lazy('accounts:Module_Auth_login')


@require_POST
def logout_view(request):
    logout(request)
    return redirect('accounts:Module_Auth_login')
