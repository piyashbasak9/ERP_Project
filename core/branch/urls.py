from django.urls import path

from . import views

app_name = 'branch'

urlpatterns = [
    path('', views.index, name='Module_Branch_index_branch'),
    path('add/', views.add, name='Module_Branch_add_branch'),
    path('edit/<int:pk>/', views.edit, name='Module_Branch_edit_branch'),
    path('delete/<int:pk>/', views.delete, name='Module_Branch_delete_branch'),
    path('tree/', views.tree, name='Module_Branch_tree'),
    path('switch/', views.switch, name='Module_Branch_switch'),
    path('centers/', views.organization_list, {'resource': 'centers'}, name='Module_Center_list'),
    path('centers/add/', views.organization_form, {'resource': 'centers'}, name='Module_Center_add'),
    path('centers/edit/<int:pk>/', views.organization_form, {'resource': 'centers'}, name='Module_Center_edit'),
    path('groups/', views.organization_list, {'resource': 'groups'}, name='Module_Group_list'),
    path('groups/add/', views.organization_form, {'resource': 'groups'}, name='Module_Group_add'),
    path('groups/edit/<int:pk>/', views.organization_form, {'resource': 'groups'}, name='Module_Group_edit'),
    path('staff/', views.organization_list, {'resource': 'staff'}, name='Module_Staff_list'),
    path('staff/add/', views.organization_form, {'resource': 'staff'}, name='Module_Staff_add'),
    path('staff/edit/<int:pk>/', views.organization_form, {'resource': 'staff'}, name='Module_Staff_edit'),
    path('members/', views.member_list, name='Module_Members_list'),
    path('members/add/', views.member_add, name='Module_Members_add'),
    path('members/edit/<int:pk>/', views.member_edit, name='Module_Members_edit'),
    path('members/<int:pk>/', views.member_detail, name='Module_Members_detail'),
    path('members/status/<int:pk>/', views.member_status, name='Module_Members_status'),
    path('members/kyc/<int:pk>/', views.member_kyc, name='Module_Members_kyc'),
    path('members/kyc/verify/<int:document_id>/', views.member_kyc_verify, name='Module_Members_kyc_verify'),
    path('members/photo/<int:file_id>/', views.private_member_file, {'kind': 'photo'}, name='Module_Members_photo'),
    path('members/kyc/file/<int:file_id>/', views.private_member_file, {'kind': 'kyc'}, name='Module_Members_kyc_file'),
    path('day-end/', views.day_end_checklist, name='Module_Branch_day_end_checklist'),
    path('day-end/close/', views.day_end_close, name='Module_Branch_day_end_close'),
    path('day-end/reopen/', views.day_end_reopen, name='Module_Branch_day_end_reopen'),
    path('holidays/', views.holiday_list, name='Module_BranchHoliday_list'),
    path('holidays/add/', views.holiday_form, name='Module_BranchHoliday_create'),
    path('holidays/edit/<int:pk>/', views.holiday_form, name='Module_BranchHoliday_edit'),
]