from django.utils import timezone

from ERP.db import SessionLocal
from core.branch.models import Branch


class BranchReadService:
    def __init__(self, request):
        self.request = request
        self.db = SessionLocal()

    def search(self, query):
        if self.request.GET.get('name'):
            query = query.filter(Branch.name.ilike(f"%{self.request.GET.get('name')}%"))

        if self.request.GET.get('code'):
            query = query.filter(Branch.code.ilike(f"%{self.request.GET.get('code')}%"))
            
        return query

    def all(self):
        query = self.db.query(Branch).where(Branch.is_active == 1)
        query = self.search(query)
        return query.all()
    
    def get(self, id):
        return self.db.query(Branch).where(Branch.is_active == 1).filter(Branch.id == id).first()




class BranchWriteService:
    def __init__(self, request):
        self.request = request
        self.db = SessionLocal()

    def create(self, data):
        branch = Branch(**data)
        self.db.add(branch)
        self.db.commit()
        self.db.refresh(branch)
        return branch

    def update(self, id, data):
        branch = self.db.query(Branch).where(Branch.is_active == 1).filter(Branch.id == id).first()
        if not branch:
            return None
        for key, value in data.items():
            setattr(branch, key, value)
        self.db.commit()
        self.db.refresh(branch)
        return branch

    def delete(self, id):
        branch = self.db.query(Branch).where(Branch.is_active == 1).filter(Branch.id == id).first()
        if not branch:
            return None

        branch.is_active = 0
        branch.updated_at = timezone.now()
        if getattr(self.request, 'user', None) and getattr(self.request.user, 'is_authenticated', False):
            branch.updated_by = self.request.user.id

        self.db.commit()
        self.db.refresh(branch)
        return branch