from django.shortcuts import render

# Create your views here.

def index(request):
    return render(request, 'branch/index.html')

def add(request):
    return render(request, 'branch/add.html')

def edit(request, pk):
    return render(request, 'branch/edit.html', {'pk': pk})


def delete(request, pk):
    return render(request, 'branch/delete.html', {'pk': pk})
