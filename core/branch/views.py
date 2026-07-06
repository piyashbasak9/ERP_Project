from django.core.paginator import Paginator
from django.shortcuts import render
from django.http import JsonResponse
from .service import BranchReadService

# Create your views here.


def _serialize_branch(branch):
    if isinstance(branch, dict):
        return {
            'id': branch.get('id'),
            'name': branch.get('name'),
            'code': branch.get('code'),
            'is_active': branch.get('is_active'),
        }

    return {
        'id': branch.id,
        'name': branch.name,
        'code': branch.code,
        'is_active': branch.is_active,
    }



def index(request):
    data = BranchReadService(request).all()
    paginator = Paginator(list(data), 10)
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
    return render(request, 'branch/add.html')

def edit(request, pk):
    data = BranchReadService(request).get(pk)
    return render(request, 'branch/edit.html', {'pk': pk, 'data': data})


def delete(request, pk):
    return render(request, 'branch/delete.html', {'pk': pk})
