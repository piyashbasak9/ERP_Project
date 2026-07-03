from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    path('login/', views.CustomLoginView.as_view(), name='Module_Auth_login'),
    path('logout/', views.logout_view, name='Module_Auth_logout'),
    path('create-role/', views.create_role, name='Module_Auth_create_role'),
    path('roles/', views.list_roles, name='Module_Auth_list_roles'),
    path('edit-role/<int:pk>/', views.edit_role, name='Module_Auth_edit_role'),
    path('create-user/', views.create_user, name='Module_Auth_create_user'),
    path('users/', views.list_users, name='Module_Auth_list_users'),
    path('users/edit/<int:pk>/', views.edit_user, name='Module_Auth_edit_user'),
]