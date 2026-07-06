from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth import get_user_model, authenticate, login, logout
from django.contrib.auth.views import LoginView, LogoutView
from django.urls import reverse_lazy
from .forms import RoleForm, UserCreationForm
from ERP.db import SessionLocal
from .models_sa import Role, UserRole

User = get_user_model()

def create_role(request):
    if request.method == 'POST':
        form = RoleForm(request.POST)
        if form.is_valid():
            try:
                role = form.save()
            except Exception as e:
                # attach error to form for display and preserve input
                form.add_error('name', str(e))
                messages.error(request, str(e))
            else:
                role_name = role.get('name') if isinstance(role, dict) else getattr(role, 'name', str(role))
                messages.success(request, f"✅ '{role_name}' Successfully created!")
                return redirect('accounts:Module_Auth_list_roles')
        else:
            messages.error(request, "Form is not valid.")
    else:
        form = RoleForm()
    return render(request, 'accounts/create_role.html', {'form': form})


def edit_role(request, pk):
    session = SessionLocal()
    try:
        role = session.query(Role).filter(Role.id == pk).first()
        if not role:
            messages.error(request, "Role not found.")
            return redirect('accounts:Module_Auth_list_roles')
        role_data = {'id': role.id, 'name': role.name}
    finally:
        session.close()

    if request.method == 'POST':
        form = RoleForm(request.POST, role_id=pk)
        if form.is_valid():
            try:
                form.save()
            except Exception as e:
                messages.error(request, f"Could not update role: {e}")
            else:
                messages.success(request, f"✅ '{role_data.get('name')}' updated successfully!")
                return redirect('accounts:Module_Auth_list_roles')
    else:
        form = RoleForm(role_id=pk)

    return render(request, 'accounts/edit_role.html', {'form': form, 'role': role_data})


def create_user(request):
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.set_password(form.cleaned_data['password'])
            user.save()

            role_id = form.cleaned_data['role_id']
            if role_id:
                session = SessionLocal()
                try:
                    existing = session.query(UserRole).filter(UserRole.user_id == user.id).first()
                    if existing:
                        existing.role_id = role_id
                    else:
                        ur = UserRole(user_id=user.id, role_id=role_id)
                        session.add(ur)
                    session.commit()
                    messages.success(request, f"✅ '{user.username}' created and role assigned successfully!")
                except Exception as e:
                    session.rollback()
                    messages.error(request, f" Problem: {e}")
                finally:
                    session.close()
            else:
                messages.warning(request, "User created, but no role assigned.")

            return redirect('accounts:Module_Auth_list_users')
        else:
            messages.error(request, "Form is not valid.")
    else:
        form = UserCreationForm()

    return render(request, 'accounts/create_user.html', {'form': form})


def list_roles(request):
    session = SessionLocal()
    try:
        roles = session.query(Role).all()
        roles_list = [{'id': r.id, 'name': r.name, 'perm_count': len(r.permissions)} for r in roles]
    finally:
        session.close()
    return render(request, 'accounts/list_roles.html', {'roles': roles_list})


def list_users(request):
    users = User.objects.all().values('id', 'username', 'email', 'first_name', 'last_name')
    session = SessionLocal()
    try:
        user_roles = session.query(UserRole).all()
        role_map = {ur.user_id: ur.role.name for ur in user_roles if ur.role}
        for user in users:
            user['role'] = role_map.get(user['id'], 'No Role')
    finally:
        session.close()
    return render(request, 'accounts/list_users.html', {'users': users})


def edit_user(request, pk):
    try:
        user = User.objects.get(pk=pk)
    except User.DoesNotExist:
        messages.error(request, "User not found.")
        return redirect('accounts:Module_Auth_list_users')

    if request.method == 'POST':
        user.username = request.POST.get('username', user.username)
        user.email = request.POST.get('email', user.email)
        user.first_name = request.POST.get('first_name', user.first_name)
        user.last_name = request.POST.get('last_name', user.last_name)
        user.is_staff = request.POST.get('is_staff') == 'on'
        user.is_superuser = request.POST.get('is_superuser') == 'on'
        
        try:
            user.save()
            
            # update user role if provided
            role_id = request.POST.get('role_id')
            if role_id:
                session = SessionLocal()
                try:
                    existing = session.query(UserRole).filter(UserRole.user_id == user.id).first()
                    if existing:
                        existing.role_id = int(role_id)
                    else:
                        ur = UserRole(user_id=user.id, role_id=int(role_id))
                        session.add(ur)
                    session.commit()
                finally:
                    session.close()
            
            messages.success(request, f"✅ '{user.username}' updated successfully!")
            return redirect('accounts:Module_Auth_list_users')
        except Exception as e:
            messages.error(request, f"Could not update user: {e}")
    
    # fetch user's current role if any
    session = SessionLocal()
    try:
        user_role = session.query(UserRole).filter(UserRole.user_id == user.id).first()
        current_role_id = user_role.role_id if user_role else None
        all_roles = session.query(Role).all()
        roles_list = [(r.id, r.name) for r in all_roles]
    finally:
        session.close()
    
    return render(request, 'accounts/edit_user.html', {
        'user': user,
        'current_role_id': current_role_id,
        'roles': roles_list
    })


class CustomLoginView(LoginView):
    template_name = 'registration/login.html'
    redirect_authenticated_user = True
    
    def get_success_url(self):
        return reverse_lazy('Module_Home_home') or '/'


class CustomLogoutView(LogoutView):
    next_page = reverse_lazy('accounts:Module_Auth_login')


def logout_view(request):
    """Allow logout via GET and redirect to login page."""
    logout(request)
    return redirect('accounts:Module_Auth_login')