from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    path('login/', views.CustomLoginView.as_view(), name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('create-role/', views.create_role, name='create_role'),
    path('roles/', views.list_roles, name='list_roles'),
    path('edit-role/<int:pk>/', views.edit_role, name='edit_role'),
    path('create-user/', views.create_user, name='create_user'),
    path('users/', views.list_users, name='list_users'),
    path('users/edit/<int:pk>/', views.edit_user, name='edit_user'),
]