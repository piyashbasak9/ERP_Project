from django.contrib.auth.views import PasswordChangeDoneView, PasswordChangeView
from django.urls import path, reverse_lazy

from . import views

app_name = 'accounts'

urlpatterns = [
    path('login/', views.CustomLoginView.as_view(), name='Module_Auth_login'),
    path('logout/', views.logout_view, name='Module_Auth_logout'),
    path(
        'password/change/',
        PasswordChangeView.as_view(
            template_name='registration/password_change_form.html',
            success_url=reverse_lazy('accounts:Module_Auth_change_password_done'),
        ),
        name='Module_Auth_change_password',
    ),
    path(
        'password/change/done/',
        PasswordChangeDoneView.as_view(
            template_name='registration/password_change_done.html',
        ),
        name='Module_Auth_change_password_done',
    ),
    path('create-role/', views.create_role, name='Module_Auth_create_role'),
    path('roles/', views.list_roles, name='Module_Auth_list_roles'),
    path('edit-role/<int:pk>/', views.edit_role, name='Module_Auth_edit_role'),
    path('create-user/', views.create_user, name='Module_Auth_create_user'),
    path('users/', views.list_users, name='Module_Auth_list_users'),
    path('users/edit/<int:pk>/', views.edit_user, name='Module_Auth_edit_user'),
    path('users/delete/<int:pk>/', views.delete_user, name='Module_Auth_delete_user'),
]