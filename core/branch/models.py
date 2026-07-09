from sqlalchemy import Column, Integer, String, DateTime, func, select
from django.contrib.auth import get_user_model
from ERP.db import Base


class Branch(Base):
    __tablename__ = 'branches'

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, index=True, nullable=False)
    code = Column(String(10), unique=True, index=True, nullable=False)
    is_active = Column(Integer, default=1, nullable=False)
    created_by = Column(Integer, nullable=False)
    updated_by = Column(Integer, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    @property
    def created_by_name(self):
        User = get_user_model()
        user = User.objects.filter(id=self.created_by).values_list('username', flat=True).first()
        return user if user else None

    @property
    def updated_by_name(self):
        User = get_user_model()
        user = User.objects.filter(id=self.updated_by).values_list('username', flat=True).first()
        return user if user else None





