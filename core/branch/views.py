from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.contrib import messages

from .service import BranchReadService, BranchWriteService

# Create your views here.


def _serialize_branch(branch):
    branch_id = branch.get('id') if isinstance(branch, dict) else branch.id
    edit_url = reverse('branch:Module_Branch_edit_branch', args=[branch_id])
    delete_url = reverse('branch:Module_Branch_delete_branch', args=[branch_id])
    
    action_html = (
        f'<div class="d-flex gap-2 justify-content-center">'
        f'<a href="{edit_url}?popup=1" class="btn btn-sm btn-outline-primary" title="Edit">✏️</a>'
        f'<a href="{delete_url}?popup=1" class="btn btn-sm btn-outline-danger" title="Delete">🗑️</a>'
        f'</div>'
    )

    if isinstance(branch, dict):
        return {
            'id': branch.get('id'),
            'name': branch.get('name'),
            'code': branch.get('code'),
            'is_active': branch.get('is_active'),
            'created_by': branch.get('created_by'),
            'created_at': branch.get('created_at'),
            'updated_by': branch.get('updated_by'),
            'updated_at': branch.get('updated_at'),
            'actions': action_html
        }

    return {
        'id': branch.id,
        'name': branch.name,
        'code': branch.code,
        'is_active': branch.is_active,
        'created_by': branch.created_by_name if branch.created_by else None,
        'created_at': branch.created_at,
        'updated_by': branch.updated_by_name if branch.updated_by else None,
        'updated_at': branch.updated_at,
        'actions': action_html
    }



def index(request):
    data = BranchReadService(request).all()
    rows = request.GET.get('rows', 20)
    paginator = Paginator(list(data), int(rows))
    page_obj = paginator.get_page(request.GET.get('page', 1))

    if request.GET.get('ajax'):
        return JsonResponse({
            'rows': [_serialize_branch(item) for item in page_obj.object_list],
            'page': page_obj.number,
            'total': paginator.num_pages,
            'records': paginator.count,
        })

    return render(request, 'branch/index.html')



def add(request):
    if request.method == 'POST':
        data = {
            'name': request.POST.get('name'),
            'code': request.POST.get('code'),
            'is_active': request.POST.get('is_active'),
            'created_by': request.user.id,
            'updated_by': request.user.id,
            'updated_at': timezone.now(),
            'created_at': timezone.now(),
        }
        branch = BranchWriteService(request).create(data)
        messages.success(request, f"✅ '{branch.name}' Successfully created!")
        return redirect('branch:Module_Branch_index_branch')
    return render(request, 'branch/add.html')


def edit(request, pk):
    data = BranchReadService(request).get(pk)
    if request.method == 'POST':
        data = {
            'name': request.POST.get('name'),
            'code': request.POST.get('code'),
            'is_active': request.POST.get('is_active'),
            'updated_by': request.user.id,
            'updated_at': timezone.now(),
        }
        branch = BranchWriteService(request).update(pk, data)
        if branch:
            messages.success(request, f"✅ '{branch.name}' Successfully updated!")
        else:
            messages.error(request, f"❌ Failed to update branch '{branch.name}'.")
        return redirect('branch:Module_Branch_index_branch')
    return render(request, 'branch/add.html', {'pk': pk, 'data': data})



def delete(request, pk):
    if request.method == 'POST':
        branch = BranchWriteService(request).delete(pk)
        if branch:
            messages.success(request, f"✅ '{branch.name}' Successfully deleted!")
        else:
            messages.error(request, f"❌ Failed to delete branch '{branch.name}'.")
        return redirect('branch:Module_Branch_index_branch')
    return render(request, 'branch/delete.html', {'pk': pk})
