from django.contrib import messages
from django.contrib.auth import get_user_model, logout
from django.contrib.auth.views import LoginView, LogoutView
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, OuterRef, Q, Subquery
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.html import format_html, format_html_join
from django.views.decorators.http import require_POST

from core.accounts.permission_utils import user_has_route_permission
from core.common.popup import popup_json_response, render_popup_form

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
                role_id = role.get('id') if isinstance(role, dict) else role.pk
                response = popup_json_response(
                    request,
                    message=f"'{role_name}' created successfully.",
                    data={'id': role_id},
                )
                if response is not None:
                    return response
                messages.success(request, f"✅ '{role_name}' Successfully created!")
                return redirect('accounts:Module_Auth_list_roles')
        else:
            messages.error(request, 'Form is not valid.')
    else:
        form = RoleForm()
    return render_popup_form(request, 'accounts/create_role.html', {'form': form})


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
                response = popup_json_response(
                    request,
                    message=f"'{role_data.get('name')}' updated successfully.",
                    data={'id': role.pk},
                )
                if response is not None:
                    return response
                messages.success(request, f"✅ '{role_data.get('name')}' updated successfully!")
                return redirect('accounts:Module_Auth_list_roles')
    else:
        form = RoleForm(role_id=pk)

    return render_popup_form(
        request, 'accounts/edit_role.html', {'form': form, 'role': role_data}
    )


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
            response = popup_json_response(
                request,
                message=completion_message,
                data={'id': user.pk},
            )
            if response is not None:
                return response
            if role_id:
                messages.success(request, f"'{user.username}' created and role assigned successfully!")
            else:
                messages.warning(request, 'User created, but no role assigned.')

            return redirect('accounts:Module_Auth_list_users')
        messages.error(request, 'Form is not valid.')
    return render_popup_form(request, 'accounts/create_user.html', {'form': form})


def list_roles(request):
    roles = Role.objects.annotate(permission_count=Count('permissions'))
    name = request.GET.get('name', '').strip()
    if name:
        roles = roles.filter(name__icontains=name)

    order_fields = {
        'name': 'name',
        'permission_count': 'permission_count',
    }
    order = order_fields.get(request.GET.get('sidx', 'name'), 'name')
    if request.GET.get('sord', 'asc').lower() == 'desc':
        order = f'-{order}'
    try:
        page_size = min(max(int(request.GET.get('rows', 20)), 1), 200)
    except (TypeError, ValueError):
        page_size = 20
    paginator = Paginator(roles.order_by(order, 'pk'), page_size)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    if request.GET.get('ajax') == '1':
        can_edit = user_has_route_permission(
            request.user, 'Module_Auth_edit_role'
        )
        rows = []
        for role in page_obj.object_list:
            actions = []
            if can_edit:
                actions.append(format_html(
                    '<a href="{}?popup=1" data-popup data-popup-title="Edit role">'
                    'Edit</a>',
                    reverse('accounts:Module_Auth_edit_role', args=[role.pk]),
                ))
            rows.append({
                'id': role.pk,
                'name': role.name,
                'permission_count': role.permission_count,
                'actions': format_html_join(
                    ' | ', '{}', ((action,) for action in actions)
                ),
            })
        return JsonResponse({
            'rows': rows,
            'page': page_obj.number,
            'total': paginator.num_pages,
            'records': paginator.count,
        })

    return render(request, 'accounts/list_roles.html', {
        'list_title': 'Roles & permissions',
        'grid_url': request.path,
        'filter_layout': 'members',
        'default_sort_name': 'name',
        'default_sort_order': 'asc',
        'initial_page_text': f'Page {page_obj.number} of {paginator.num_pages}',
        'list_actions': [],
        'add_url': (
            reverse('accounts:Module_Auth_create_role')
            if user_has_route_permission(
                request.user, 'Module_Auth_create_role'
            )
            else ''
        ),
        'add_title': 'Create role',
        'list_filters': [
            {
                'name': 'name', 'label': 'Role name',
                'value': name, 'placeholder': 'Role name',
            },
        ],
        'list_columns': [
            {'name': 'name', 'label': 'Role name', 'width': 240},
            {
                'name': 'permission_count', 'label': 'Permission count',
                'width': 160,
            },
            {'name': 'actions', 'label': 'Actions', 'width': 90},
        ],
    })


def list_users(request):
    manageable_user_ids = [
        user.pk
        for user in users_visible_to(request).only('id', 'branch_id')
        if user_access_is_manageable(request, user)
    ]
    users = User.objects.filter(pk__in=manageable_user_ids).annotate(
        role_name=Subquery(
            UserRole.objects.filter(user_id=OuterRef('pk')).values('role__name')[:1]
        )
    )
    username = request.GET.get('username', '').strip()
    name = request.GET.get('name', '').strip()
    email = request.GET.get('email', '').strip()
    role = request.GET.get('role', '').strip()
    status = request.GET.get('status', '').strip()
    if username:
        users = users.filter(username__icontains=username)
    if name:
        users = users.filter(
            Q(first_name__icontains=name) | Q(last_name__icontains=name)
        )
    if email:
        users = users.filter(email__icontains=email)
    if role:
        users = users.filter(role_name__icontains=role)
    if status in {'active', 'inactive'}:
        users = users.filter(is_active=status == 'active')

    order_fields = {
        'username': 'username',
        'name': 'first_name',
        'email': 'email',
        'role': 'role_name',
        'status': 'is_active',
    }
    order = order_fields.get(request.GET.get('sidx', 'username'), 'username')
    if request.GET.get('sord', 'asc').lower() == 'desc':
        order = f'-{order}'
    try:
        page_size = min(max(int(request.GET.get('rows', 20)), 1), 200)
    except (TypeError, ValueError):
        page_size = 20
    paginator = Paginator(
        users.order_by(order, 'last_name', 'pk'), page_size
    )
    page_obj = paginator.get_page(request.GET.get('page', 1))

    if request.GET.get('ajax') == '1':
        can_edit = user_has_route_permission(
            request.user, 'Module_Auth_edit_user'
        )
        can_delete = user_has_route_permission(
            request.user, 'Module_Auth_delete_user'
        )
        rows = []
        for user in page_obj.object_list:
            actions = []
            if can_edit:
                actions.append(format_html(
                    '<a href="{}?popup=1" data-popup data-popup-title="Edit user" '
                    'data-popup-width="900" data-popup-height="760">Edit</a>',
                    reverse('accounts:Module_Auth_edit_user', args=[user.pk]),
                ))
            if can_delete:
                actions.append(format_html(
                    '<a href="{}" data-confirm data-confirm-title="Delete user" '
                    'data-confirm-message="Delete user \'{}\'? This action cannot '
                    'be undone." data-confirm-button="Delete">Delete</a>',
                    reverse('accounts:Module_Auth_delete_user', args=[user.pk]),
                    user.username,
                ))
            rows.append({
                'id': user.pk,
                'username': user.username,
                'role': user.role_name or 'No Role',
                'email': user.email,
                'name': ' '.join(
                    value for value in (user.first_name, user.last_name) if value
                ),
                'status': 'Active' if user.is_active else 'Inactive',
                'actions': format_html_join(
                    ' | ', '{}', ((action,) for action in actions)
                ),
            })
        return JsonResponse({
            'rows': rows,
            'page': page_obj.number,
            'total': paginator.num_pages,
            'records': paginator.count,
        })

    return render(request, 'accounts/list_users.html', {
        'list_title': 'Users',
        'grid_url': request.path,
        'filter_layout': 'members',
        'default_sort_name': 'username',
        'default_sort_order': 'asc',
        'initial_page_text': f'Page {page_obj.number} of {paginator.num_pages}',
        'list_actions': [],
        'add_url': (
            reverse('accounts:Module_Auth_create_user')
            if user_has_route_permission(
                request.user, 'Module_Auth_create_user'
            )
            else ''
        ),
        'add_title': 'Create user',
        'list_filters': [
            {
                'name': 'username', 'label': 'Username',
                'value': username, 'placeholder': 'Username',
            },
            {
                'name': 'name', 'label': 'Name',
                'value': name, 'placeholder': 'Name',
            },
            {
                'name': 'email', 'label': 'Email',
                'value': email, 'placeholder': 'Email',
            },
            {
                'name': 'role', 'label': 'Role',
                'value': role, 'placeholder': 'Role',
            },
            {
                'name': 'status', 'label': 'Status', 'type': 'select',
                'value': status,
                'options': (('active', 'Active'), ('inactive', 'Inactive')),
            },
        ],
        'list_columns': [
            {'name': 'username', 'label': 'Username', 'width': 150},
            {'name': 'name', 'label': 'Name', 'width': 180},
            {'name': 'role', 'label': 'Role', 'width': 150},
            {'name': 'email', 'label': 'Email', 'width': 220},
            {'name': 'status', 'label': 'Status', 'width': 100},
            {'name': 'actions', 'label': 'Actions', 'width': 130},
        ],
    })


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
        response = popup_json_response(
            request,
            message=f"'{user.username}' updated successfully.",
            data={'id': user.pk},
        )
        if response is not None:
            return response
        return redirect('accounts:Module_Auth_list_users')
    return render_popup_form(
        request, 'accounts/edit_user.html', {'user': user, 'form': form}
    )


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

class CustomLogoutView(LogoutView):
    next_page = reverse_lazy('accounts:Module_Auth_login')


@require_POST
def logout_view(request):
    logout(request)
    return redirect('accounts:Module_Auth_login')
