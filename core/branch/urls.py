from django.urls import path
from . import views

app_name = 'branch'

urlpatterns = [
    path('', views.index, name='Module_Branch_index_branch'),
    path('add/', views.add, name='Module_Branch_add_branch'),
    path('edit/<int:pk>/', views.edit, name='Module_Branch_edit_branch'),
    path('delete/<int:pk>/', views.delete, name='Module_Branch_delete_branch')
]