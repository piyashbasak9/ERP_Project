import base64
import io
import secrets
import time

import qrcode
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, logout
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.views import LoginView, LogoutView
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme, urlencode
from django.views.decorators.http import require_POST
from django_otp.plugins.otp_totp.models import TOTPDevice

from core.audit.services import log_action
from core.common.popup import popup_json_response, render_popup_form

from .forms import RoleForm, UserCreationForm, UserEditForm
from .mfa import confirmed_totp_device, user_requires_mfa
from .models import RecoveryCode, Role, UserRole

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

    def get_success_url(self):
        if user_requires_mfa(self.request.user):
            route_name = (
                'Module_Auth_mfa_verify'
                if confirmed_totp_device(self.request.user)
                else 'Module_Auth_mfa_setup'
            )
            next_url = super().get_success_url()
            return f'{reverse_lazy(f"accounts:{route_name}")}?{urlencode({"next": next_url})}'
        return super().get_success_url()


class CustomLogoutView(LogoutView):
    next_page = reverse_lazy('accounts:Module_Auth_login')


def _mfa_lock_key(user):
    return f'accounts:mfa-failures:{user.pk}'


def _mfa_failure_timeout():
    return int(getattr(settings, 'MFA_COOLOFF_SECONDS', 900))


def _mfa_is_locked(user):
    return cache.get(_mfa_lock_key(user), 0) >= int(
        getattr(settings, 'MFA_FAILURE_LIMIT', 5)
    )


def _record_mfa_failure(user):
    key = _mfa_lock_key(user)
    if not cache.add(key, 1, timeout=_mfa_failure_timeout()):
        cache.incr(key)


def _mfa_success(request):
    cache.delete(_mfa_lock_key(request.user))
    request.session['mfa_verified_at'] = int(time.time())


def _safe_mfa_next(request):
    next_url = request.POST.get('next') or request.GET.get('next') or '/'
    if not url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return '/'
    return next_url


def _recovery_codes(user):
    codes = [secrets.token_hex(5).upper() for _ in range(10)]
    RecoveryCode.objects.bulk_create(
        [RecoveryCode(user=user, code_hash=make_password(code)) for code in codes]
    )
    return codes


def _recovery_code_is_valid(user, submitted):
    for code in RecoveryCode.objects.select_for_update().filter(
        user=user, used_at__isnull=True
    ):
        if check_password(submitted, code.code_hash):
            code.used_at = timezone.now()
            code.save(update_fields=['used_at'])
            return True
    return False


def _qr_data_uri(otp_uri):
    image = qrcode.make(otp_uri)
    output = io.BytesIO()
    image.save(output, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(output.getvalue()).decode('ascii')


def mfa_setup(request):
    if not user_requires_mfa(request.user):
        return redirect('/')
    device = TOTPDevice.objects.filter(user=request.user, name='primary').first()
    if device and device.confirmed:
        return redirect('accounts:Module_Auth_mfa_verify')
    if device is None:
        device = TOTPDevice.objects.create(user=request.user, name='primary', confirmed=False)

    recovery_codes = None
    error = ''
    if request.method == 'POST':
        if _mfa_is_locked(request.user):
            return HttpResponse('Too many verification attempts. Try again later.', status=429)
        token = request.POST.get('token', '').strip()
        verified = False
        if token.isdigit():
            with transaction.atomic():
                device = TOTPDevice.objects.select_for_update().get(
                    pk=device.pk,
                    user=request.user,
                )
                device.confirmed = True
                device.save(update_fields=['confirmed'])
                verified = device.verify_token(token)
                if verified:
                    RecoveryCode.objects.filter(user=request.user).delete()
                    recovery_codes = _recovery_codes(request.user)
                else:
                    device.confirmed = False
                    device.save(update_fields=['confirmed'])
        if verified:
            _mfa_success(request)
        else:
            _record_mfa_failure(request.user)
            error = 'The verification code was not accepted.'

    return render(
        request,
        'registration/mfa_setup.html',
        {
            'qr_data_uri': _qr_data_uri(device.config_url),
            'manual_key': device.key,
            'error': error,
            'recovery_codes': recovery_codes,
            'next_url': _safe_mfa_next(request),
        },
    )


def mfa_verify(request):
    if not user_requires_mfa(request.user):
        return redirect('/')
    device = confirmed_totp_device(request.user)
    if device is None:
        return redirect('accounts:Module_Auth_mfa_setup')

    error = ''
    if request.method == 'POST':
        if _mfa_is_locked(request.user):
            return HttpResponse('Too many verification attempts. Try again later.', status=429)
        token = request.POST.get('token', '').strip()
        verified = False
        if token.isdigit():
            with transaction.atomic():
                locked_device = TOTPDevice.objects.select_for_update().get(
                    pk=device.pk,
                    user=request.user,
                    confirmed=True,
                )
                verified = locked_device.verify_token(token)
        if not verified and token:
            with transaction.atomic():
                verified = _recovery_code_is_valid(request.user, token)
        if verified:
            _mfa_success(request)
            return redirect(_safe_mfa_next(request))
        _record_mfa_failure(request.user)
        error = 'The verification code was not accepted.'

    return render(
        request,
        'registration/mfa_verify.html',
        {'error': error, 'next_url': _safe_mfa_next(request)},
    )


def mfa_admin_reset(request, user_id):
    if not user_requires_mfa(request.user):
        return HttpResponse('An administrator MFA session is required.', status=403)
    if request.user.pk == user_id:
        return HttpResponse('Another administrator must reset your MFA.', status=400)
    if not request.session.get('mfa_verified_at'):
        return redirect('accounts:Module_Auth_mfa_verify')

    target = get_object_or_404(users_visible_to(request), pk=user_id)
    if request.method == 'POST':
        reason = request.POST.get('reason', '').strip()
        if not reason:
            return render(
                request,
                'accounts/mfa_reset.html',
                {'target': target, 'error': 'A reason is required.'},
                status=400,
            )
        with transaction.atomic():
            TOTPDevice.objects.filter(user=target).delete()
            RecoveryCode.objects.filter(user=target).delete()
            log_action(
                'MFAReset',
                'CustomUser',
                target.pk,
                new_values={'mfa_enrollment_required': True},
                remarks=reason,
            )
        cache.delete(_mfa_lock_key(target))
        messages.success(request, 'The user must enroll in MFA at their next login.')
        return redirect('accounts:Module_Auth_list_users')

    return render(request, 'accounts/mfa_reset.html', {'target': target})


@require_POST
def logout_view(request):
    logout(request)
    return redirect('accounts:Module_Auth_login')
